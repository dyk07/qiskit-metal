# Latest Commit Insight: `60eee1f`

分析对象：`D:/BaiduSyncdisk/vsCOde/circuit/qiskit/qiskit-metal-worktrees/dyk07-main`

提交信息：

- Commit: `60eee1f0126bda9aa1fc047311a0e79eebfad164`
- Message: `add json function`
- Author/Committer: `dyk07 <dengyk25@mails.tsinghua.edu.cn>`
- Commit date: `2026-04-25 21:06:10 +0800`
- 当前分支：`work/dyk07-main`

当前工作区在分析时已有未提交改动：

- `src/qiskit_metal/renderers/renderer_mpl/mpl_renderer.py`：已暂存修改
- `test.ipynb`：未暂存修改

本文只分析 `HEAD` 最新提交本身，不评价这些未提交改动。

## 一句话结论

这个提交把 Qiskit Metal 的保存/加载路径从“只支持 pickle”扩展成“按文件扩展名选择 JSON 文本 schema 或 legacy pickle”：`.json` / `.txt` 走新 JSON schema，其他扩展名保留原 pickle 行为。它还提交了一个可加载的 JSON 示例设计、一个实际为 pickle binary 的 `my_design.metal.json`，以及一个 notebook 演示从 JSON 加载后导出 GDS。

## 变更范围

本次提交涉及 4 个文件：

- `src/qiskit_metal/toolbox_metal/import_export.py`
  - 主要实现文件。
  - 从 70 行左右扩展到 548 行左右。
  - 新增 JSON schema 描述、保存、加载、校验、组件重建、连接恢复等逻辑。

- `example_chip_design.metal.json`
  - 新增文本 JSON 示例文件。
  - schema 格式为 `qiskit-metal.design-description`，版本 `1`。
  - 包含 `15` 个组件、`14` 条连接，设计类为 `qiskit_metal.designs.design_planar.DesignPlanar`。

- `my_design.metal.json`
  - 新增文件，但内容不是 JSON 文本，而是 pickle/binary。
  - 由于新逻辑会把 `.json` 扩展名交给 `load_metal_json()`，这个文件名和内容类型存在冲突。

- `test.ipynb`
  - 新增一个 notebook。
  - 演示路径：插入本地 `src` 到 `sys.path`，调用 `load_metal_design("example_chip_design.metal.json")`，创建 `MetalGUI`，再使用 `QGDSRenderer` 导出 `example_chip_design.gds`。

## 新增 API 和常量

`import_export.py` 新增/暴露：

- `DESIGN_DESCRIPTION_FORMAT = "qiskit-metal.design-description"`
- `DESIGN_DESCRIPTION_VERSION = 1`
- `describe_metal_design(design)`
- `describe_metal_text(design, indent=2)`
- `validate_design_payload(payload)`
- `save_metal_json(filename, design, indent=2)`
- `load_metal_json(filename)`

已有 API 的行为变化：

- `save_metal(filename, design)`
  - 如果文件名以 `.json` 或 `.txt` 结尾，调用 `save_metal_json()`。
  - 否则保留 pickle 保存逻辑。

- `load_metal_design(filename)`
  - 如果文件名以 `.json` 或 `.txt` 结尾，调用 `load_metal_json()`。
  - 否则保留 pickle 加载逻辑。

这意味着上层 `QDesign.save_design()` 和 `QDesign.load_design()` 不需要修改调用方式，但会因为路径扩展名不同而进入不同序列化后端。

## JSON Schema 结构

新 schema 的顶层结构是：

```json
{
  "format": "qiskit-metal.design-description",
  "version": 1,
  "generated_utc": "...",
  "design": {},
  "components": [],
  "connections": []
}
```

`design` 保存：

- 设计类完整路径，例如 `qiskit_metal.designs.design_planar.DesignPlanar`
- 设计名
- `save_path`
- `overwrite_enabled`
- `enable_renderers`
- `metadata`
- `variables`
- `chips`
- 从构造函数参数里提取的 `init_kwargs`

`components` 保存每个组件：

- `id`
- `name`
- `class`
- `made`
- `status`
- `options`
- `metadata`
- `pins`
- `init_kwargs`

`connections` 保存 netlist 连接：

- `net_id`
- 两个 endpoint
- 每个 endpoint 包含组件名和 pin 名

注意：schema 没有直接保存 `qgeometry` 表。加载时依赖重新实例化组件并调用组件自身的 `make()` 流程来重建几何。

## 保存执行路径

从普通用户调用出发：

```text
design.save_design("xxx.json")
-> QDesign.save_design()
-> save_metal(path, design)
-> _is_text_serialization_path(path)
-> save_metal_json(path, design)
-> describe_metal_design(design)
-> validate_design_payload(payload)
-> json.dump(payload)
```

保存时主要数据来源：

- `design._components`
  - 遍历组件 id，读取组件名、类路径、options、metadata、pins、status。

- `design.net_info`
  - 按 `net_id` 分组，转成组件名 + pin 名的 endpoint。

- `design.metadata / design.variables / design.chips`
  - 作为设计级数据写入 payload。

- `inspect.signature(instance.__class__.__init__)`
  - 尝试从实例属性中反推构造函数参数，写入 `init_kwargs`。

`_to_jsonable()` 负责把 numpy、dict、tuple、set、array-like 等值转成 JSON 可保存的普通 Python 类型。

## 加载执行路径

从普通用户调用出发：

```text
QDesign.load_design("xxx.json")
-> load_metal_design(path)
-> _is_text_serialization_path(path)
-> load_metal_json(path)
-> json.load()
-> validate_design_payload(payload)
-> _instantiate_design_from_payload(payload["design"])
-> _deserialize_components(design, payload["components"])
-> _deserialize_connections(design, payload["connections"])
```

加载时的数据落点：

- 设计对象：
  - 根据 `design["class"]` 动态 import 设计类并实例化。
  - 更新 `metadata`、`variables`、`chips`。
  - 设置 `design.save_path`。
  - 恢复 `design.logger`。

- 组件对象：
  - 根据组件 `class` 动态 import 类。
  - 传入 `design`、`name`、`options`、`make` 和可用的 `init_kwargs`。
  - 如果组件 metadata 存在，更新到 `component.metadata`。
  - 如果未 make 或组件 pins 为空，则用序列化 pins 恢复。

- 连接信息：
  - 先调用 `design.delete_all_pins()` 清空 net 信息并把已有 pins 的 `net_id` 归零。
  - 再用组件名查 id。
  - 最后调用 `design.connect_pins()` 重新建立连接。

## 示例文件观察

`example_chip_design.metal.json` 是新 schema 的真实示例：

- `format`: `qiskit-metal.design-description`
- `version`: `1`
- `design.class`: `qiskit_metal.designs.design_planar.DesignPlanar`
- `components`: `15`
- `connections`: `14`
- `variables`: `cpw_gap`, `cpw_width`
- `chips`: `main`
- 前几个组件：
  - `Q1`: `TransmonPocketCL`
  - `Q2`: `TransmonPocketCL`
  - `Bus_Q1_Q2`: `RoutePathfinder`
  - `Cap_Q1`: `Cap3Interdigital`
  - `Cap_Q2`: `Cap3Interdigital`

`test.ipynb` 中的演示代码加载的是这个 JSON 文件，并在 `enable_renderers=false` 时手动创建 `QGDSRenderer`，然后导出 GDS。

## 主要风险和注意点

1. `my_design.metal.json` 的内容类型与扩展名冲突

   这个文件是 binary/pickle 内容，不是 JSON。由于新逻辑把 `.json` 交给 `load_metal_json()`，直接加载它会触发 JSON 解析失败。建议改扩展名，或不要把 legacy pickle 文件命名为 `.json`。

2. 按扩展名分流会改变历史文件兼容性

   如果过去有人把 pickle 文件保存成 `.json` 或 `.txt`，新版本会尝试按 JSON 读取，导致无法加载。可以考虑在 JSON 解析失败后做一次 pickle fallback，但这需要明确安全策略，因为 pickle 加载本身有代码执行风险。

3. `qgeometry` 没有被直接序列化

   这个设计更像“可重建 design description”，不是完整 runtime snapshot。只要组件类和 options 能稳定重建几何，结果就合理；如果用户手动改过 `design.qgeometry` 表，或者组件构建依赖外部状态，这些变化不会被 JSON 保存。

4. 动态 import 依赖类路径稳定

   schema 保存的是完整 Python 类路径。组件或设计类移动模块后，旧 JSON 会加载失败，除非提供兼容 import path 或迁移层。

5. `init_kwargs` 是启发式提取

   `_extract_init_kwargs()` 通过构造函数签名和实例属性反推参数。这个方式对常规类有帮助，但不能保证覆盖所有自定义构造参数，尤其是通过 `**kwargs`、派生属性或延迟初始化保存的数据。

6. 连接恢复依赖组件名和 pin 名

   `_deserialize_connections()` 使用组件名查 id，再检查 pin 名是否存在。只要加载后组件 make 出来的 pin 名和保存时一致，就可以恢复；如果组件 options 变化导致 pin 名不一致，连接会被跳过。

7. `enable_renderers` 被简化成 bool

   保存时记录的是 `bool(design._renderers)`，不是最初构造时的完整 renderer 配置。示例 JSON 中 `enable_renderers=false`，所以 notebook 需要手动创建 GDS renderer。

## 建议补充验证

优先补以下测试：

- 保存一个简单 `DesignPlanar + TransmonPocket` 到 `.json`，再加载，确认组件数、组件名、options、pins、net_info 一致。
- 保存/加载带连接的设计，确认 `connect_pins()` 恢复出的 net 数量和 endpoint 正确。
- `.metal` 或其他非 `.json/.txt` 后缀仍走 pickle legacy path。
- 一个 `.json` 后缀但内容不是 JSON 的文件，应有明确错误信息。
- `example_chip_design.metal.json` 能通过 `load_metal_design()` 加载并导出 GDS。

## 推荐下一步

- 先处理 `my_design.metal.json`：改名为 pickle 后缀，或重新导出为真正 JSON。
- 给 `load_metal_design()` 的扩展名分流策略补测试，避免未来把 legacy pickle 误当 JSON。
- 明确文档措辞：当前 JSON schema 是 design description / reconstructable schema，不是包含全部 qgeometry runtime 状态的全量快照。
