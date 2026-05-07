# Qiskit Metal Design DSL

把"用 Python 一行行 `TransmonPocket(design, ...)` 拼出芯片"换成"写一份 YAML 描述文件"。这不是导入/导出工具——它是 Python 构建路径的**第二条**入口，与原 API 平等共存。

- 实现：`src/qiskit_metal/toolbox_metal/design_dsl.py`
- 示例：`examples/dsl/2x2_4qubit.metal.yaml`（4-qubit 2x2 阵列，70 行 YAML 顶替原 230 行 Python）
- 跑通脚本：`examples/dsl/run_2x2_demo.py`
- 全链示例：`examples/dsl/chain_2q_full.metal.yaml`（Hamiltonian→Circuit→Netlist→Geometry）
- Netlist-only 示例：`examples/dsl/chain_2q_netlist.metal.yaml`（无路由、只连 pin）
- 跑通脚本：`examples/dsl/run_chain_demo.py`

## 与现有路径的关系

| 用途 | 走哪条 |
|---|---|
| 用 Python 编程式构建 | 原 `TransmonPocket(design, ...)` API，照旧 |
| 手写一份完整设计的 YAML 描述 | 本 DSL（`build_design("design.yaml")`） |
| 把已构建的 design 存档 / 回放 | `import_export.py` 里的 `save_metal` / `load_metal_design`（旧 commit 已加 JSON snapshot） |

DSL 与 snapshot 是不同的层次：DSL 是**作者意图**（紧凑、有模板和循环），snapshot 是**完整状态**（每个 option、每个 pin 几何全部展开）。

## 最小用法

```python
from qiskit_metal.toolbox_metal.design_dsl import build_design

design = build_design("examples/dsl/2x2_4qubit.metal.yaml")

# 返回的就是普通 QDesign，可以继续 Python 端追加：
from qiskit_metal.qlibrary.qubits.transmon_pocket import TransmonPocket
TransmonPocket(design, "Q5", options={"pos_x": "3mm", "pos_y": "0mm"})
```

注册自定义组件类：

```python
from qiskit_metal.toolbox_metal.design_dsl import register_component
register_component("MyTransmon", MyTransmonClass)
# 之后 YAML 里写 class: MyTransmon 即可
```

构建后钩子（用于做一些 DSL 不便表达的修补）：

```python
def _tweak(design):
    design.delete_all_pins()
build_design("design.yaml", post_build=_tweak)
```

也可在调用时打 patch（譬如批量改 vars 来扫参）：

```python
build_design("design.yaml", overrides={"vars": {"qx": "2mm"}})
```

## DSL 顶层结构

```yaml
schema: qiskit-metal/design-dsl/1   # 可选，loader 会校验前缀

design:
  class: DesignPlanar               # 短名（见下方注册表）或完整 dotted path
  overwrite_enabled: true
  enable_renderers: true
  variables: {cpw_width: 12um, cpw_gap: 7um}
  chip:
    size: 10mm x 10mm                # 也可写 {size_x: 10mm, size_y: 10mm}
                                     # 或 [10mm, 10mm]

vars:                                # 仅供 ${...} 字符串插值，不进 design.variables
  qx: 1.55mm

templates:                           # 可被 $extend 引用的复用块
  qubit:
    class: TransmonPocket
    options: {pad_width: 425um}
  bus_route:
    class: RouteMeander
    options: {trace_width: 12um}

components:                          # 顺序实例化
  - {name: Q1, $extend: qubit, options: {pos_x: -1mm}}

routes:                              # 默认 class=RouteMeander，from/to 自动展开
  - {name: bus, $extend: bus_route, from: Q1.bus, to: Q2.bus,
     options: {total_length: 5mm}}
```

## Hamiltonian–Circuit–Netlist–Geometry 全链（v2）

v2 保持 v1 兼容，但把几何相关字段收进 `geometry:`，并新增 `hamiltonian`/`circuit`/`netlist`。
这些层的数据会被挂到 `design.metadata['dsl_chain']`，方便分析或导出。

```yaml
schema: qiskit-metal/design-dsl/2

vars:
  qx: 1.2mm
  c_q: 65fF
  ej_q: 18GHz

hamiltonian:
  subsystems:
    Q1: {model: transmon, EJ: "${ej_q}", C: "${circuit.Q1.C}"}

circuit:
  Q1: {type: transmon, C: "${c_q}"}

netlist:
  connections:
    - {from: Q1.bus, to: Q2.bus}

geometry:
  design:
    class: DesignPlanar
    chip: {size: 6mm x 6mm}
  templates:
    qubit: {class: TransmonPocket, options: {pad_width: 420um}}
  components:
    - {name: Q1, $extend: qubit, options: {pos_x: -${qx}}}
```

**电路信息上下传的方式**：

- 通过共享 `vars` 或引用 `circuit.*`/`hamiltonian.*`（点路径插值）。
- `netlist.connections` 仅在没有路由的情况下建议使用；路由会自动写入 netlist。
- 如果需要“几何 -> 电路”的回写，可在 `post_build` 钩子里读取 geometry 信息再更新 `design.metadata['dsl_chain']`。

## 保留 key（DSL directives）

### `$extend: <模板名>`
深合并 templates 中的某一份模板。模板自身也可以 `$extend` 形成链。循环引用会报错。

```yaml
templates:
  base:   {class: TransmonPocket, options: {pad_width: 425um}}
  variant: {$extend: base, options: {pad_height: 90um}}  # 链式
```

### `$for: [<dict>, ...]`
循环展开：列表里每个 dict 是一轮的局部变量，可以在循环体里用 `${name}` 引用。**循环体就是 `$for` 的 sibling 键**——没有单独的 `$emit` 块，省一层缩进。

```yaml
- $for:
    - {name: Q1, x: -1mm}
    - {name: Q2, x: +1mm}
  $extend: qubit
  name: ${name}
  options: {pos_x: ${x}}
```

### `$include: <相对路径>`
把另一份 YAML 文件嵌入当前位置。**整节点必须只有 $include 一个键**。仅支持文件源（直接传 YAML 文本时不可用）。

```yaml
templates:
  $include: shared_templates.yaml
```

### `${name}` 字符串插值
任意字符串里都可以写 `${var}`，按 "**循环局部变量 → vars → hamiltonian/circuit/netlist**" 优先级查找。
支持点路径：`${circuit.Q1.C}`。
未知变量会报错（不会静默留 `${...}` 在结果里）。

不做算术——算术留给 Metal 自己的 sympy parser，写 `"3 * cpw_width"` 这种就行。

## 路由简记 `from` / `to`

```yaml
routes:
  - {name: bus, from: Q1.bus, to: Q2.bus, options: {total_length: 5mm}}
```

`from: "Q1.bus"` 自动展为：
```yaml
options:
  pin_inputs:
    start_pin: {component: Q1, pin: bus}
    end_pin:   {component: Q2, pin: bus}   # 同理来自 to
```

如果 `options.pin_inputs` 已经写了某个 endpoint，简记**不会覆盖**显式写法。

`class` 缺省时默认 `RouteMeander`。要换路由类型，在 spec 里写 `class: RoutePathfinder` 即可。

## 内置短名注册表

设计类（`design.class`）：
- `DesignPlanar`、`DesignFlipChip`、`DesignMultiPlanar`

组件类（`class:` 字段，常用挑选）：
- Qubits：`TransmonPocket`、`TransmonPocketCL`、`TransmonPocket6`、`TransmonPocketTeeth`、`TransmonCross`、`TransmonCrossFL`、`TransmonConcentric`、`TransmonInterdigitated`、`StarQubit`
- Routes：`RouteMeander`、`RouteStraight`、`RouteAnchors`、`RoutePathfinder`、`RouteMixed`、`RouteFramed`
- Terminations：`OpenToGround`、`ShortToGround`、`LaunchpadWirebond`、`LaunchpadWirebondCoupled`、`LaunchpadWirebondDriven`
- Couplers：`CoupledLineTee`、`LineTee`、`CapNInterdigitalTee`、`TunableCoupler01`、`TunableCoupler02`

短名表外的类，写完整 dotted path 也可以：

```yaml
components:
  - {name: my, class: my_pkg.my_module.MyComp, options: {...}}
```

## YAML 写作的几个坑

- **维度量永远带单位**。`total_length: 5` 会是 int 5；写 `total_length: 5mm` 才是 string `"5mm"`。
- **避免 YAML 1.1 真值陷阱**。只用 `true` / `false`，**不要**写 `yes` / `no` / `on` / `off`，那些会被 PyYAML 解析成 bool 但语义未必是你想要的。loader 不主动把 bool 转成字符串——一些 component options 期望字符串 `"true"`/`"false"`，请显式加引号。
- **带号字符串建议加引号**：`loc_W: "+1"` 比 `loc_W: +1`（→ int 1，丢符号）更稳。
- **flow 风格里 `${var}` 必须加引号**。`{pos_x: ${qx}}` 会因为 `{` 撞 flow-map 分隔符而 YAML 解析失败；写 `{pos_x: "${qx}"}` 或换 block 风格。block 风格 `pos_x: ${qx}` 不需要引号。
- **`avoid_collision`** 写真 bool（`avoid_collision: false`）能正好绕过 upstream 那个字符串 truthy bug；这是 DSL 自带的副作用，不需要额外注意。

## 与 Python 端继续协作

`build_design()` 返回的 `design` 是普通 QDesign 实例，所以：

- 可以追加组件：`TransmonPocket(design, "Q5", options=...)`
- 可以挂 GUI：`MetalGUI(design); gui.rebuild(); gui.autoscale()`
- 可以走 GDS / HFSS renderer：照原 API
- 可以再次 `save_metal(design, "snapshot.metal.json")` 走 snapshot path 存档
