# Qiskit Metal DSL v3 示例教程

这个目录演示 Qiskit Metal 的 native YAML DSL v3 怎么写、怎么运行、以及数据最终会落到哪里。

核心结论:

```text
YAML DSL
  -> build_ir()
  -> DesignIR
  -> build_design() / export_ir_to_metal()
  -> Metal QDesign
```

DSL v3 不再把 qlibrary Python class 当作 YAML 的 build target。也就是说，不写:

```yaml
components:
  Q1:
    class: TransmonPocket
```

而是写两类 native 结构:

```yaml
# 1. primitive-native: 每个 shape/pin 都手写
components:
  Q1:
    primitives: [...]
    pins: [...]

# 2. YAML-native component template: 由 YAML 模板生成 primitives/pins
components:
  Q1:
    type: transmon_pocket
    options: {...}
```

注意: 这不是删除 Metal core，也不是删除 qlibrary 源码。当前变化只是 DSL 作者入口和 build target 不再是 qlibrary Python class。导出结果仍然是普通 Metal `QDesign`，几何仍然写到 `design.qgeometry.tables`，pin 仍然写到 `design.components[name].pins`，连接仍然写到 `design.net_info`。

## 1. 目录里的文件

### `native_2q_minimal.metal.yaml`

最小 primitive-native 两量子位例子。

适合第一眼学习 DSL v3 的基本结构:

- `vars`
- `hamiltonian`
- `circuit`
- `netlist`
- `geometry.design`
- `geometry.components.*.primitives`
- `geometry.components.*.pins`

它不使用 `type: transmon_pocket`，也不使用 qlibrary `class`。

### `chain_2q_native.metal.yaml`

Hamiltonian-Circuit-Netlist-Geometry full-chain 例子。

它展示:

- `hamiltonian` 引用 `circuit`。
- `geometry` 引用 `circuit` 和 `vars`。
- `netlist` 把 `Q1.bus -> bus.start -> bus.end -> Q2.bus` 串起来。
- `geometry.templates` 和 `$extend` 做 primitive 片段复用。
- bus component 用 `path.polyline` 建中心导体和 subtract gap。

### `transmon_pocket_2q.metal.yaml`

YAML-native `TransmonPocket` 例子。

它展示:

- 用 `type: transmon_pocket` 代替 qlibrary `class: TransmonPocket`。
- 内置模板继承链:

```text
qcomponent.yaml -> base_qubit.yaml -> transmon_pocket.yaml
```

- `connection_pads.readout` 自动生成:

```text
readout_connector_pad
readout_wire
readout_wire_sub
readout pin
```

### `run_chain_demo.py`

运行 full-chain primitive-native 示例，打印:

- schema
- component names
- qgeometry row counts
- net rows
- derived metadata keys

### `run_transmon_pocket_demo.py`

运行 YAML-native TransmonPocket 示例，打印:

- component types
- template inheritance
- qgeometry row names
- generated pins
- net rows
- metadata keys

### `dsl_v3_*.md`

这些是汇报/讲解材料，放在这里便于现场打开。它们不是 DSL 运行必需文件。

## 2. 快速运行

先进入 worktree:

```powershell
cd D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main
```

运行 primitive full-chain 示例:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

预期输出类似:

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

运行 YAML-native TransmonPocket 示例:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

预期输出类似:

```text
schema       : qiskit-metal/design-dsl/3
components   : ['Q1', 'Q2']
types        : {'Q1': 'transmon_pocket', 'Q2': 'transmon_pocket'}
templates    : {'Q1': {'type': 'transmon_pocket', 'inherited': ['qcomponent', 'base_qubit', 'transmon_pocket']}, ...}
poly rows    : 8 [...]
path rows    : 4 [...]
junction rows: 2 [...]
pins         : {'Q1': ['readout'], 'Q2': ['readout']}
net rows     : 2
PASS: YAML-native TransmonPocket template exported to Metal
```

运行测试:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
```

## 3. Python API 怎么用

最常用的两个函数:

```python
from qiskit_metal.toolbox_metal.design_dsl import build_ir, build_design

ir = build_ir("examples/dsl/chain_2q_native.metal.yaml")
design = build_design("examples/dsl/chain_2q_native.metal.yaml")
```

`build_ir()` 返回 `DesignIR`，适合检查 DSL 解析结果:

```python
print(ir.schema)
print([component.name for component in ir.components])
print(ir.derived)
```

`build_design()` 返回普通 Metal `QDesign`，适合继续使用 Metal 的 qgeometry、renderer、analysis 生态:

```python
print(design.qgeometry.tables["poly"])
print(design.components["Q1"].pins)
print(design.net_info)
print(design.metadata["dsl_chain"])
```

## 4. 一个 DSL 文件的基本结构

最外层 schema 必须是:

```yaml
schema: qiskit-metal/design-dsl/3
```

推荐结构:

```yaml
schema: qiskit-metal/design-dsl/3

vars:
  qx: 1.2mm

hamiltonian:
  subsystems: {}
  couplings: []

circuit:
  Q1: {}

netlist:
  connections:
    - {from: Q1.bus, to: Q2.bus}

geometry:
  design:
    class: DesignPlanar
    chip: {size: 6mm x 6mm}
  components:
    Q1:
      primitives: []
      pins: []
```

### 4.1 `vars`

`vars` 是全局变量表。

```yaml
vars:
  pad_w: 420um
  trace_w: 12um
```

引用:

```yaml
size: ["${vars.pad_w}", 90um]
width: "${trace_w}"
```

说明:

- `${vars.pad_w}` 是完整路径写法。
- `${pad_w}` 也可用，因为 root vars 会被展开到上下文顶层。
- 单位字符串会被 Metal parser 转成内部数值，通常以 mm 为长度单位。

### 4.2 `circuit`

`circuit` 放电路层参数。它可以引用 `vars`。

```yaml
circuit:
  Q1: {type: transmon, C: 65fF, pad_width: "${vars.pad_w}"}
  bus: {width: 12um, gap: 7um}
```

geometry 可以引用 circuit:

```yaml
width: "${circuit.bus.width}"
size: ["${circuit.Q1.pad_width}", 90um]
```

### 4.3 `hamiltonian`

`hamiltonian` 放物理/模型层 metadata。它可以引用 `vars` 和 `circuit`。

```yaml
hamiltonian:
  subsystems:
    Q1: {model: transmon, EJ: 18GHz, C: "${circuit.Q1.C}"}
```

当前它主要是结构化 metadata，不会自动做物理求解。

### 4.4 `netlist`

`netlist.connections` 用 `component.pin` 写法描述连接:

```yaml
netlist:
  connections:
    - {from: Q1.readout, to: Q2.readout}
```

导出时会:

1. 检查 `Q1` 和 `Q2` 是否存在。
2. 检查 `readout` pin 是否存在。
3. 调用 `design.connect_pins()`。
4. 把连接写入 `design.net_info`。

当前连接条目只接受 `from` 和 `to`。roles、coupler metadata 等属于后续 schema 扩展。

### 4.5 `geometry.design`

`geometry.design` 描述 Metal design:

```yaml
geometry:
  design:
    class: DesignPlanar
    chip: {size: 6mm x 6mm}
```

常用字段:

- `class`: `DesignPlanar`、`DesignFlipChip`、`DesignMultiPlanar`，也可以注册自定义 design。
- `chip`: 芯片尺寸和中心。
- `variables`: 覆盖 Metal design variables。
- `metadata`
- `overwrite_enabled`
- `enable_renderers`

### 4.6 `geometry.components`

有两种写法。

primitive-native:

```yaml
components:
  Q1:
    primitives:
      - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [420um, 90um]}
    pins:
      - {name: bus, points: [[0.2mm, -6um], [0.2mm, 6um]], width: 12um}
```

YAML-native component template:

```yaml
components:
  Q1:
    type: transmon_pocket
    options:
      pos_x: -1.2mm
      connection_pads:
        readout:
          loc_W: 1
          loc_H: 1
```

不要写 qlibrary class:

```yaml
# v3 native DSL 会拒绝这种写法
Q1:
  class: TransmonPocket
```

## 5. Primitive 怎么写

### 5.1 矩形 poly

```yaml
- name: pad
  type: poly.rectangle
  center: [0mm, 0mm]
  size: [420um, 90um]
  layer: 1
```

写入:

```python
design.qgeometry.tables["poly"]
```

### 5.2 多边形 poly

```yaml
- name: tri
  type: poly.polygon
  points: [[0mm, 0mm], [1mm, 0mm], [0mm, 1mm]]
```

### 5.3 path

```yaml
- name: center_trace
  type: path.polyline
  points: [[0mm, 0mm], [1mm, 0mm], [1mm, 1mm]]
  width: 12um
```

`path.line` / `path.polyline` 必须提供 `width`。

### 5.4 junction

```yaml
- name: jj
  type: junction.line
  points: [[0mm, -45um], [0mm, 45um]]
  width: 10um
```

`junction.line` 必须提供两个点和 `width`。

### 5.5 subtract / helper / chip / layer

```yaml
- name: pocket
  type: poly.rectangle
  center: [0mm, 0mm]
  size: [800um, 520um]
  subtract: true
  helper: false
  chip: main
  layer: 1
```

`subtract: true` 会写入 qgeometry 表的 subtract 字段，表示刻蚀/挖空区域。

## 6. Pin 怎么写

### 6.1 显式 tangent points

最常用:

```yaml
pins:
  - name: bus
    points: [[0.34mm, -6um], [0.34mm, 6um]]
    width: 12um
    gap: 7um
```

要点:

- points 必须是两个点。
- 两点距离应等于 `width`。
- `gap` 可省略；省略时默认为 `0.6 * width`。

### 6.2 normal_segment

模板 generator 常用:

```yaml
pins:
  - name: readout
    mode: normal_segment
    from_operation: placed.connector_wire_path
    segment: last
    width: 12um
```

含义:

- 从 operation 输出的 LineString 取最后一段。
- 最后一段的方向作为 pin normal。
- 导出时调用 `add_pin(..., input_as_norm=True)`。

普通手写 DSL 初学者可以先不用这个模式。

## 7. Transform 怎么写

component 级:

```yaml
Q1:
  translate: [-1.2mm, 0mm]
  rotate: 90
```

或者:

```yaml
Q1:
  transform:
    translate: [-1.2mm, 0mm]
    rotate: 90
    origin: [0mm, 0mm]
```

primitive/pin 也可以有自己的 `transform`。最终会先应用局部 transform，再应用 component transform。

在 `type: transmon_pocket` 中，更推荐使用继承自 `qcomponent.yaml` 的 options:

```yaml
options:
  pos_x: -1.2mm
  pos_y: 0mm
  orientation: 90
```

## 8. `$include`、`$for`、`$extend`

这套 primitive-native 片段复用能力适合简单 YAML 复用。

### 8.1 `$include`

```yaml
geometry:
  templates:
    $include: templates.yaml
```

`$include` 只能在 build_ir() 输入为文件路径时使用，因为它需要相对路径。

### 8.2 `$for`

```yaml
components:
  - $for:
      - {name: Q1, x: -1mm}
      - {name: Q2, x: 1mm}
    name: "${name}"
    translate: ["${x}", 0mm]
```

### 8.3 `$extend`

```yaml
geometry:
  templates:
    pad_pair:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [400um, 90um]}
  components:
    Q1:
      $extend: pad_pair
```

注意:

- `$extend` 是局部 YAML 片段复用。
- `type: transmon_pocket` 是 component template 系统。
- 写复杂组件时优先考虑 component template。

## 9. YAML-native `type: transmon_pocket`

最小写法:

```yaml
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
```

带位置和 readout pad:

```yaml
geometry:
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: -1.2mm
        pos_y: 0mm
        orientation: 0
        connection_pads:
          readout:
            loc_W: 1
            loc_H: 1
            cpw_width: 12um
            cpw_gap: 7um
```

继承链:

```text
qcomponent:
  pos_x / pos_y / orientation / chip / layer / transform

base_qubit:
  connection_pads
  _default_connection_pads
  merge rule: each connection pad inherits defaults

transmon_pocket:
  pad_gap / inductor_width / pad_width / pad_height
  pocket_width / pocket_height
  static pad/pocket/junction primitives
  connection_pads generator
```

`connection_pads.readout` 会生成:

```text
poly:
  pad_top
  pad_bot
  rect_pk
  readout_connector_pad

path:
  readout_wire
  readout_wire_sub

junction:
  rect_jj

pin:
  readout
```

## 10. 插值和表达式

简单引用:

```yaml
width: "${vars.trace_w}"
```

引用嵌套对象:

```yaml
width: "${circuit.bus.width}"
```

单位算术:

```yaml
center: [0mm, "${(options.pad_height + options.pad_gap) / 2}"]
width: "${pad.value.cpw_width + 2 * pad.value.cpw_gap}"
```

支持的表达式是受限安全表达式，不是任意 Python。不要写函数调用或 import。

## 11. 数据最终写到哪里

`build_ir()` 后:

```python
ir.components                  # ComponentIR 列表
ir.components[0].primitives    # PrimitiveIR
ir.components[0].pins          # PinIR
ir.derived                     # bounds、path length、pin middle、netlist 等
```

`build_design()` 后:

```python
design.qgeometry.tables["poly"]
design.qgeometry.tables["path"]
design.qgeometry.tables["junction"]
design.components["Q1"].pins
design.net_info
design.metadata["dsl_chain"]
```

`design.metadata["dsl_chain"]` 是调试 DSL 最重要的位置。它包含:

- `schema`
- `vars`
- `hamiltonian`
- `circuit`
- `netlist`
- `design`
- `geometry`
- `derived`

## 12. 常见错误

### 12.1 写了 qlibrary class

错误:

```yaml
Q1:
  class: TransmonPocket
```

原因:

DSL v3 native components 不接受 qlibrary class entries。请改成:

```yaml
Q1:
  type: transmon_pocket
```

或者手写 primitives/pins。

### 12.2 netlist pin 不存在

错误:

```yaml
netlist:
  connections:
    - {from: Q1.nope, to: Q2.bus}
```

原因:

`Q1` 中没有名为 `nope` 的 pin。需要先在 `geometry.components.Q1.pins`
里定义，或者确认 template generator 会生成这个 pin。

### 12.3 path/junction 没有 width

错误:

```yaml
- name: trace
  type: path.line
  points: [[0mm, 0mm], [1mm, 0mm]]
```

修正:

```yaml
- name: trace
  type: path.line
  points: [[0mm, 0mm], [1mm, 0mm]]
  width: 12um
```

### 12.4 pin points 距离和 width 不一致

错误:

```yaml
points: [[0mm, -6um], [0mm, 6um]]
width: 20um
```

两点距离是 12um，但 width 写了 20um。改成:

```yaml
width: 12um
```

## 13. 推荐学习顺序

1. 读 `native_2q_minimal.metal.yaml`，理解 DSL 的五个顶层 section。
2. 跑 `run_chain_demo.py`，看 qgeometry/netlist 输出。
3. 读 `chain_2q_native.metal.yaml`，理解 full chain 和 `$extend`。
4. 读 `transmon_pocket_2q.metal.yaml`，理解 `type: transmon_pocket`。
5. 跑 `run_transmon_pocket_demo.py`，看 template inheritance 和 generated rows。
6. 读 `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`，看 YAML 模板如何生成 connection pads。
7. 读测试:

```text
tests/test_design_dsl.py
tests/test_design_dsl_templates.py
tests/test_design_dsl_transmon_pocket.py
```

## 14. 面向汇报的一句话

可以这样总结:

“DSL v3 把 Qiskit Metal 设计描述变成了一个可测试的编译链路: YAML 先解析成 DesignIR，再导出到 Metal QDesign。TransmonPocket 不再由 DSL 直接实例化 Python qlibrary class，而是由 YAML-native 模板生成 primitive geometry、pins 和 netlist，最后仍然落在 Metal core 的 qgeometry、pins 和 net_info 上。”

