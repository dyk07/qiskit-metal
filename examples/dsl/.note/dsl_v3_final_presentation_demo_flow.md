# DSL v3 / YAML-native TransmonPocket 汇报与演示流程

目标 worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

本文面向现场汇报和演示。建议把最近 8 次提交当成一个合并后的工作包来讲:

```text
1d0399e9 dsl v3-0
99772d82 fixing dsl v3-0
a8aeaf41 Add DSL template infrastructure checkpoint
dc009420 Advance DSL template operations checkpoint
9879755d Add YAML TransmonPocket template checkpoint
f0204796 Add TransmonPocket DSL example and parity tests
b3dba972 fix bugs
90955f47 simplify
```

一句话总结:

这轮工作把 Qiskit Metal DSL v3 从“primitive YAML 示例”推进成了“YAML-native 组件模板链路”: YAML 先解析成独立 IR，再导出到普通 Metal `QDesign`; DSL authoring/build target 不再是 qlibrary Python class，而是 YAML template + primitive IR，同时保留 Metal core、qgeometry、pin、netlist 和 renderer 可用的设计对象。

## 1. 这次工作的目标

原始需求可以拆成两条主线。

第一条是打通 Hamiltonian-Circuit-Netlist-Geometry full chain:

```text
vars
  -> circuit
  -> hamiltonian
  -> netlist
  -> geometry
  -> primitive IR
  -> Metal QDesign
  -> derived metadata
```

它解决的是“参数和连接关系如何从上层语义一路落到几何和 Metal 运行时对象”的问题。

第二条是 remove qlibrary as DSL build target:

```text
旧 DSL 思路:
YAML class: TransmonPocket
  -> Python qlibrary TransmonPocket(...)
  -> make()

当前 v3 思路:
YAML type: transmon_pocket
  -> qcomponent.yaml
  -> base_qubit.yaml
  -> transmon_pocket.yaml
  -> primitive/pin IR
  -> NativeComponent + qgeometry + pins + net_info
```

注意汇报时一定要讲清楚: 这里不是删除 Metal core，也不是删除 qlibrary 源码。我们移除的是“把 qlibrary Python class 当作 DSL 作者直接填写和 build 的目标”。导出阶段仍然进入标准 Metal `QDesign`; 只是组件实例是轻量 `NativeComponent`，几何由 YAML template 编译后的 primitive 写入。

## 2. 汇报主线

建议按三段演示:

1. Primitive chain: 先证明 v3 full chain 已经能从 Hamiltonian/Circuit/Netlist/Geometry 走到 qgeometry/net_info。
2. YAML-native TransmonPocket: 再证明原本依赖 qlibrary `TransmonPocket` 的组件可以由 YAML template 生成。
3. Parity tests: 最后证明 YAML-native 的 TransmonPocket 与原 qlibrary 参考实现一致，并且 build 时不会实例化 qlibrary class。

这一顺序比较稳: 先讲底层链路，再讲高级模板，最后讲可信度。

## 3. 演示前准备

打开终端:

```powershell
cd D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main
git status --short --branch
git log --oneline -8
```

当前确认过的状态:

```text
## full_chain...origin/full_chain
```

`.codex/` 当前是 ignored，不被 git track。汇报文档产物放在 `.codex/` 是符合要求的。

推荐先告诉听众:

“下面演示用的是 conda 里的 metal-env Python，避免环境差异影响 Qiskit Metal、PySide、shapely 这些依赖。”

Python 路径:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe
```

## 4. 演示一: Primitive Full Chain

### 4.1 打开/展示文件

先打开:

```text
examples/dsl/chain_2q_native.metal.yaml
examples/dsl/run_chain_demo.py
src/qiskit_metal/toolbox_metal/design_dsl.py
src/qiskit_metal/toolbox_metal/dsl/builder.py
```

展示重点:

- `chain_2q_native.metal.yaml` 里同时有 `hamiltonian`、`circuit`、`netlist`、`geometry`。
- `hamiltonian.subsystems.Q1.C` 引用 `circuit.Q1.C`。
- `geometry.components` 用 primitive 显式描述 pad、pocket、junction、bus。
- `netlist.connections` 把 `Q1.bus -> bus.start`、`bus.end -> Q2.bus` 连起来。
- `run_chain_demo.py` 调用 `build_ir()` 和 `build_design()`，然后检查 qgeometry 和 netlist。
- `design_dsl.py` 已经只是兼容 facade，真正实现进入 `dsl/builder.py`。

### 4.2 运行命令

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

当前已重新运行，预期输出:

```text
schema       : qiskit-metal/design-dsl/3
components   : ['Q1', 'Q2', 'bus']
poly rows    : 6
path rows    : 2
junction rows: 2
net rows     : 4
derived keys : ['circuit', 'netlist']
PASS: native DSL chain exported to Metal
```

### 4.3 推荐话术

可以这样讲:

“第一段先不碰 TransmonPocket。这里只看 DSL v3 的最小能力: YAML 里有 circuit 和 hamiltonian 参数，也有 netlist 和 primitive geometry。`build_ir()` 先把这些都解析成一个稳定的 `DesignIR`; `build_design()` 再把 IR 写进 Metal 的 `QDesign`。输出里 qgeometry 三张表都有行，net rows 也生成了，说明这个链路已经不是只解析 YAML，而是实际落到了 Metal 对象图里。”

然后指出:

“这一步的价值是把 DSL 变成一个小型 compiler: 前端是 YAML/schema/interpolation/template，后端是 Metal qgeometry/pins/net_info。”

## 5. 演示二: YAML-native TransmonPocket

### 5.1 打开/展示文件

打开:

```text
examples/dsl/transmon_pocket_2q.metal.yaml
examples/dsl/run_transmon_pocket_demo.py
src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml
src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml
src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml
src/qiskit_metal/toolbox_metal/dsl/component_templates.py
src/qiskit_metal/toolbox_metal/dsl/template_registry.py
```

展示 YAML 示例:

```yaml
geometry:
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: "-${vars.qx}"
        connection_pads:
          readout:
            loc_W: 1
            loc_H: 1
            cpw_width: "${vars.cpw_width}"
            cpw_gap: "${vars.cpw_gap}"
```

这里要强调两个点:

- 用户写的是 `type: transmon_pocket`，不是 `class: TransmonPocket`。
- `readout` 不是手写 primitive，而是 template generator 从 `connection_pads` 生成 connector pad、wire、subtract wire 和 pin。

展示模板继承:

```text
qcomponent.yaml
  -> base_qubit.yaml
  -> transmon_pocket.yaml
```

每层职责:

- `qcomponent.yaml`: 提供 `pos_x`、`pos_y`、`orientation`、`chip`、`layer` 和通用 transform。
- `base_qubit.yaml`: 提供 `connection_pads` 和“每个 pad 继承默认 pad 配置”的 merge rule。
- `transmon_pocket.yaml`: 提供 pocket/pad/junction primitive 以及 connection pad generator。

### 5.2 运行命令

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

当前已重新运行，预期输出:

```text
schema       : qiskit-metal/design-dsl/3
components   : ['Q1', 'Q2']
types        : {'Q1': 'transmon_pocket', 'Q2': 'transmon_pocket'}
templates    : {'Q1': {'type': 'transmon_pocket', 'inherited': ['qcomponent', 'base_qubit', 'transmon_pocket']}, 'Q2': {'type': 'transmon_pocket', 'inherited': ['qcomponent', 'base_qubit', 'transmon_pocket']}}
poly rows    : 8 ['pad_bot', 'pad_bot', 'pad_top', 'pad_top', 'readout_connector_pad', 'readout_connector_pad', 'rect_pk', 'rect_pk']
path rows    : 4 ['readout_wire', 'readout_wire', 'readout_wire_sub', 'readout_wire_sub']
junction rows: 2 ['rect_jj', 'rect_jj']
pins         : {'Q1': ['readout'], 'Q2': ['readout']}
net rows     : 2
metadata     : ['circuit', 'derived', 'design', 'geometry', 'hamiltonian', 'netlist', 'schema', 'vars']
PASS: YAML-native TransmonPocket template exported to Metal
```

### 5.3 推荐话术

可以这样讲:

“第二段演示的是这轮工作的关键升级: TransmonPocket 不再作为 Python class 被 DSL 直接构造。YAML 只声明 `type: transmon_pocket`。模板系统读取内置 YAML 模板，先继承 `qcomponent` 的位置/旋转/层信息，再继承 `base_qubit` 的 connection_pads 规则，最后由 `transmon_pocket.yaml` 生成 pad、pocket、junction 和 readout pin。”

接着解释输出:

“这里的 `templates` 字段证明两个组件都走了同一条继承链。qgeometry rows 里出现了 `pad_top`、`pad_bot`、`rect_pk`、`rect_jj`，还有生成出来的 `readout_connector_pad`、`readout_wire`、`readout_wire_sub`。pins 里每个 qubit 都有 `readout`，net rows 为 2，说明 pin 确实被 connect 到同一个 Metal net 里。”

## 6. 演示三: Parity Tests

### 6.1 打开/展示文件

打开:

```text
tests/test_design_dsl.py
tests/test_design_dsl_templates.py
tests/test_design_dsl_transmon_pocket.py
```

重点展示 `tests/test_design_dsl_transmon_pocket.py`:

- `test_two_transmon_template_example_builds_native_components_and_netlist`
- `test_yaml_transmon_pocket_matches_qlibrary_geometry_and_pin`

说明:

- 第一类测试检查示例 build 后是 `NativeComponent`，不是 qlibrary `TransmonPocket`。
- 第二类测试把 YAML-native 结果与 qlibrary `TransmonPocket` 参考实现对比。
- qlibrary 在这里仅作为 test oracle，不作为 DSL build target。

### 6.2 运行命令

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
```

当前已重新运行，预期摘要:

```text
121 passed, 8 warnings in 10.01s
```

warnings 为 Qt high-DPI 和 shapely `resolution` deprecation warning，不是本轮功能失败。

### 6.3 推荐话术

可以这样讲:

“最后用测试回答两个核心质疑。第一，YAML-native TransmonPocket 是否真的没有实例化 qlibrary class? 测试断言 build 出来的组件类名是 `NativeComponent`，并且已有 no-qlibrary-construction 覆盖。第二，它和原来的 TransmonPocket 是否一致? 测试在多个 orientation 和 connection pad quadrant 下，把 qgeometry 和 pin 的 points/middle/normal/tangent/width/gap 与 qlibrary 参考实现逐项比较。”

## 7. 关键概念解释

### 7.1 “移除 qlibrary 作为 DSL build target”到底是什么意思

推荐固定话术:

“我们没有删除 qlibrary，也没有绕开 Metal core。删除的是 DSL 文件里 `class: TransmonPocket` 这种作者入口和 build 入口。现在作者写 `type: transmon_pocket`; builder 解析 YAML template，生成 primitive/pin IR，再导出到 `QDesign`。Metal core 里的 qgeometry、pin、net_info 仍然是最终承载。”

可以画成:

```text
不是:
YAML -> TransmonPocket(...) -> make()

而是:
YAML -> template expansion -> PrimitiveIR/PinIR -> NativeComponent -> QDesign
```

### 7.2 Hamiltonian/Circuit/Netlist/Geometry 如何上下传播

下行传播:

```text
vars
  -> circuit 插值
  -> hamiltonian 插值
  -> netlist 插值
  -> geometry/template/options 插值
  -> primitive/pin 数值解析
```

上行记录:

```text
primitive bounds/path length/pin middle/pin points/netlist normalized endpoint
  -> ir.derived
  -> design.metadata["dsl_chain"]["derived"]
```

导出后:

```text
qgeometry rows -> design.qgeometry.tables
pins           -> design.components[name].pins
connections    -> design.net_info
metadata        -> design.metadata["dsl_chain"]
```

## 8. 可能被问到的问题和推荐回答

### Q1. 和原 qlibrary `TransmonPocket` 是否一致?

回答:

“当前 parity 测试用原 qlibrary `TransmonPocket` 作为参考，对 YAML-native 生成的 poly/path/junction geometry、subtract、width，以及 readout pin 的 points/middle/normal/tangent/width/gap 做了比较。覆盖了多个 orientation 和 pad 方位。这里 qlibrary 只在测试里当 oracle，正常 DSL build 不会构造 qlibrary `TransmonPocket`。”

### Q2. 默认值如何继承?

回答:

“组件模板按 `qcomponent -> base_qubit -> transmon_pocket` parent-first 展开。`component_templates.py` 先合并 parent defaults，再合并 child defaults，最后合并实例 `options`。`qcomponent` 提供位置、旋转、chip、layer; `base_qubit` 提供 connection_pads; `transmon_pocket` 提供 pad_gap、pad_width、pocket_width 等 TransmonPocket 默认值。”

### Q3. `connection_pads` 怎么生成?

回答:

“`base_qubit.yaml` 定义 `connection_pads` 的 map-entry merge rule: 每个 pad entry 都继承 `_default_connection_pads`。`transmon_pocket.yaml` 里有 `generators.connection_pads`，对 `options.connection_pads` 做 for_each。每个 entry 生成 connector pad、center trace、subtract trace，以及一个 `normal_segment` pin。”

### Q4. 默认 `cpw_width` 和 `cpw_gap` 从哪里来?

回答:

“如果实例没有显式提供，它会通过 selected Metal design variables 解析，例如 `DesignPlanar` 的默认 `cpw_width`、`cpw_gap`。这点之前有 parity gap，后来已经修复并加了测试。示例里为了演示可读性，显式从 root `vars` 传了 `cpw_width` 和 `cpw_gap`。”

### Q5. 为什么 generated pin 的 gap 不是直接等于 `cpw_gap`?

回答:

“为了匹配 qlibrary `QComponent.add_pin()` 的默认行为，YAML generated pin 不显式设置 gap，而是让 `add_pin()` 走默认 `0.6 * width`。这个 parity gap 已经修复并验证。”

### Q6. `netlist` 是怎么变成 Metal 连接的?

回答:

“`build_ir()` 会把 `Q1.readout` 这样的 endpoint 规范化成 `{component: Q1, pin: readout}`，并校验 pin 存在。`export_ir_to_metal()` 创建 `NativeComponent`、添加 pins 后，调用 `design.connect_pins(...)`。成功后 `net_id` 会写回 derived netlist metadata。”

### Q7. 还有没有 qlibrary class 入口?

回答:

“v3 native geometry 显式拒绝 component 里出现 `class`。如果 YAML 写 `class: TransmonPocket` 这种 legacy shape，测试覆盖为失败。当前入口是 primitive-native component 或 YAML-native `type` template。”

### Q8. 这次工作最大的工程价值是什么?

回答:

“它把 DSL 从某个 Python 组件构造器的包装，推进成可测试、可解释、可追踪的 compiler pipeline。IR 可以单独看，导出可以单独测，metadata 能回看全链路。”

## 9. 现场演示建议时间分配

10 分钟版本:

```text
1 min  背景和一句话结论
2 min  primitive chain demo
3 min  YAML-native TransmonPocket demo
2 min  parity tests
2 min  Q&A: qlibrary removal, defaults, connection_pads, metadata
```

15 分钟版本:

```text
2 min  最近 8 次 commit 作为一个工作包的概览
3 min  build_design -> build_ir -> export_ir_to_metal 执行路径
3 min  primitive chain demo
4 min  YAML template inheritance + TransmonPocket demo
2 min  parity tests
1 min  known risks / next steps
```

## 10. 本次重新验证结果

在目标 worktree 下已重新运行:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
```

结果:

```text
run_chain_demo.py:
PASS: native DSL chain exported to Metal

run_transmon_pocket_demo.py:
PASS: YAML-native TransmonPocket template exported to Metal

pytest:
121 passed, 8 warnings in 10.01s
```

