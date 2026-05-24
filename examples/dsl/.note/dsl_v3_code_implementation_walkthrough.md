# DSL v3 / YAML-native TransmonPocket 代码实现详解

目标 worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

本文面向“快速读懂代码实现”。建议把最近 8 次提交合起来看成一个工作包: 先建立 DSL v3 primitive full chain，再抽出 package/facade，再加入 YAML component template、表达式、geometry operations、generators，最后落到 YAML-native `transmon_pocket` 示例和 parity tests。

最短理解:

```text
build_design(source)
  -> build_ir(source)
  -> YAML load/include/schema/interpolation
  -> template expansion
  -> primitive/pin IR
  -> derived metadata
  -> export_ir_to_metal(ir)
  -> NativeComponent + qgeometry + pins + net_info
  -> design.metadata["dsl_chain"]
```

## 1. 顶层执行路径图

### 1.1 一句话版本

`build_design()` 是端到端入口; `build_ir()` 把 YAML 编译成独立 `DesignIR`; `export_ir_to_metal()` 把 `DesignIR` 写进标准 Metal `QDesign`。

### 1.2 展开版本

```text
examples/dsl/*.metal.yaml
  |
  v
qiskit_metal.toolbox_metal.design_dsl.build_design()
  |
  v
dsl.builder.build_design()
  |
  v
dsl.builder.build_ir()
  |-- _load_yaml()
  |-- _expand_includes()
  |-- schema/root key validation
  |-- walk_substitute(vars/circuit/hamiltonian/netlist)
  |-- _design_variable_context()
  |-- ComponentTemplateRegistry(...)
  |-- _parse_components()
        |-- expand_component_template()
        |-- template inheritance/options merge
        |-- evaluate_geometry_operations()
        |-- _expand_component_generators()
        |-- _primitive_from_spec()
        |-- _pin_from_spec()
  |-- _derive()
  |-- _validate_netlist_endpoints()
  |
  v
DesignIR
  |
  v
dsl.builder.export_ir_to_metal()
  |-- _instantiate_design()
  |-- NativeComponent(design, name, make=False)
  |-- design.qgeometry.add_qgeometry(...)
  |-- component.add_pin(...)
  |-- design.connect_pins(...)
  |-- design.metadata["dsl_chain"] = ir.to_metadata()
  |
Metal QDesign
```

### 1.3 对应原 qlibrary 路径

旧的读代码路径大概是:

```text
TransmonPocket(design, "Q1")
  -> BaseQubit.__init__()
  -> QComponent.__init__()
  -> rebuild()
  -> TransmonPocket.make()
  -> add_qgeometry()
  -> add_pin()
```

现在 DSL v3 的 YAML-native template 路径是:

```text
YAML type: transmon_pocket
  -> ComponentTemplateRegistry.resolve("transmon_pocket")
  -> qcomponent.yaml
  -> base_qubit.yaml
  -> transmon_pocket.yaml
  -> expand_component_template()
  -> _parse_components()
  -> _primitive_from_spec() / _pin_from_spec()
  -> export_ir_to_metal()
  -> NativeComponent + qgeometry/pins/net_info
```

二者最终都写入 Metal core 的 qgeometry 和 pins; 差异在于“几何生成逻辑来自哪里”。旧路径来自 Python class `make()`; 新路径来自 YAML template 编译后的 IR。

## 2. 关键文件职责

### 2.1 `src/qiskit_metal/toolbox_metal/design_dsl.py`

这是 backward-compatible facade。

它只做一件事: 从 `qiskit_metal.toolbox_metal.dsl` re-export 公共 API，例如:

```python
build_ir
export_ir_to_metal
build_design
DesignIR
PrimitiveIR
PinIR
ComponentIR
NativeComponent
GeometryOperationRegistry
```

读代码时不要在这里找实现，直接跳到 `src/qiskit_metal/toolbox_metal/dsl/`。

### 2.2 `src/qiskit_metal/toolbox_metal/dsl/__init__.py`

这是 package public API。它把 builder、template、expression、geometry operation 的公共对象汇总成一个包级入口。

用途:

- 让 `design_dsl.py` facade 简单稳定。
- 让外部代码可以从 `qiskit_metal.toolbox_metal.dsl` 直接导入较低层工具。

### 2.3 `src/qiskit_metal/toolbox_metal/dsl/builder.py`

这是主编译器和导出器。它仍然是最大文件，建议按函数群读，而不是从头硬读到尾。

主要数据类:

- `PrimitiveIR`: 一个已解析的 primitive，含 component、name、kind、shape、shapely geometry、subtract、layer、chip、width 等。
- `PinIR`: 一个已解析的 pin，含 points、normal_points、width、gap、chip、input_as_norm。
- `ComponentIR`: 一个组件容器，含 primitives、pins、metadata、type、options、template、inherited。
- `DesignIR`: 整个 DSL 文档的 resolved IR，含 schema、vars、hamiltonian、circuit、netlist、design、components、geometry、derived。
- `NativeComponent`: 轻量 `QComponent` 子类，用来承载 native DSL 生成的 qgeometry 和 pins; `make()` 为空。

主入口:

- `build_ir(source, overrides=None)`
- `export_ir_to_metal(ir, post_build=None)`
- `build_design(source, overrides=None, post_build=None)`

核心内部函数:

- `_load_yaml()` / `_expand_includes()`: 加载 YAML 和 include。
- `_expand_list()` / `_expand_node()`: 处理 legacy inline `$extend`、`$for`。
- `_parse_components()`: 每个 component 的总控。
- `_primitive_from_spec()`: primitive YAML -> `PrimitiveIR`。
- `_pin_from_spec()`: pin YAML -> `PinIR`。
- `_expand_component_generators()`: 例如 connection pads 的批量生成。
- `_derive()`: 从 primitive/pin/netlist 计算 metadata。
- `_instantiate_design()`: 生成 Metal `DesignPlanar` 等 design。

### 2.4 `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`

这是 typed component expansion 层。它回答这个问题:

“当 YAML 写 `type: transmon_pocket` 时，如何把模板 defaults、metadata、geometry、merge rules 和实例 options 合成一个普通 component spec?”

核心入口:

```python
expand_component_template(component_spec, registry)
```

内部步骤:

1. 读取 `component_spec["type"]`。
2. 用 `registry.inheritance_chain(type)` 拿到 parent-first 模板链。
3. 合并每层 template 的:
   - `options`
   - `metadata`
   - `geometry`
   - `merge_rules`
4. 用实例 `options` 覆盖 defaults。
5. 应用 merge rules，例如 `connection_pads.each_entry_extends`。
6. 拼接 template primitives/pins 和 instance primitives/pins。
7. 返回 `ComponentTemplateExpansion`，里面有 expanded spec、resolved options、template id、inherited chain。

关键点:

`connection_pads` 不是普通 deep merge。它的规则是“每个 entry 都继承 `_default_connection_pads`”，因此用户可以只写:

```yaml
connection_pads:
  readout:
    loc_W: -1
```

最终 `readout` 会补齐 cpw_width、cpw_gap、loc_H、pad_width 等默认值。

### 2.5 `src/qiskit_metal/toolbox_metal/dsl/template_registry.py`

这是 template lookup 层。它知道 template 从哪里找。

内置模板表:

```python
BUILTIN_COMPONENT_TEMPLATE_PATHS = {
    "qcomponent": Path("core/qcomponent.yaml"),
    "base_qubit": Path("core/base_qubit.yaml"),
    "transmon_pocket": Path("qubits/transmon_pocket.yaml"),
}
```

查找顺序:

1. 当前 DSL 文档里 inline `templates`，但只收 schema 是 `qiskit-metal/component-template/1` 的 typed component template。
2. 内置模板目录 `src/qiskit_metal/toolbox_metal/dsl_templates/`。
3. 如果 `build_ir()` 输入是文件，则可以按设计文件目录查找本地 template 文件。

它还负责:

- 校验 template `id` 是否和请求的 `type` 一致。
- 检测 `extends` cycle。
- 缓存解析后的 `ComponentTemplate`。

### 2.6 `src/qiskit_metal/toolbox_metal/dsl/template_model.py`

这是 component template schema model。

它定义:

```python
TEMPLATE_SCHEMA = "qiskit-metal/component-template/1"
ComponentTemplate
component_template_from_mapping()
```

一个 template 允许的顶层 key:

```text
schema
id
extends
options
metadata
merge_rules
geometry
```

`geometry` 允许:

```text
primitives
pins
transform
operations
generators
```

它的主要作用是“早失败”: 模板如果写错 key 或类型不对，在进入 builder 前就抛 `DesignDslError`。

### 2.7 `src/qiskit_metal/toolbox_metal/dsl/expression.py`

这是安全表达式和插值层。

支持:

- `${vars.qx}` 这种 dotted path。
- `${options.pad_width / 2}` 这种有限算术。
- `${1mm + 20um}` 这种单位字面量。
- dict/list/string 的递归替换。

不支持:

- 任意 Python 调用。
- `__import__`、函数调用、复杂语法。

关键函数:

- `resolve_path(ctx, path)`
- `evaluate_expression(expr, ctx)`
- `substitute_string(value, ctx, preserve_type=True)`
- `walk_substitute(node, ctx)`

为什么重要:

`transmon_pocket.yaml` 里大量几何公式都是靠这里工作，例如:

```yaml
center: [0um, "${(options.pad_height + options.pad_gap) / 2}"]
width: "${pad.value.cpw_width + 2 * pad.value.cpw_gap}"
```

### 2.8 `src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py`

这是通用 shapely/draw geometry operation registry。

核心入口:

- `GeometryOperationRegistry`
- `evaluate_geometry_operations()`
- `resolve_operation_reference()`
- `DEFAULT_GEOMETRY_OPERATIONS`

内置 operation:

```text
rectangle
polyline
line
polygon
buffer
scale
translate
rotate
rotate_position
last_segment
transform_group
```

为什么需要它:

TransmonPocket connection pad 不是单个 rectangle 就能写完。它需要先生成局部 pad、wire path，再根据 `loc_W/loc_H` 镜像和平移，最后由 primitive/pin 引用这些操作输出。

`transform_group` 是生成 connection pad 时最关键的组合操作: 对一组 geometry 依次 scale/translate/rotate，输出一组可引用结果。

### 2.9 `src/qiskit_metal/toolbox_metal/dsl/_helpers.py`

这是 private helper 层。它集中放:

- duplicate YAML key rejection loader。
- `deep_merge()`。
- `reject_unknown_keys()`。
- `parse_number()`、`parse_point()`、`parse_points()`、`parse_angle()`、`parse_bool()`。

最近 bug fix 后，这里会更严格地拒绝 bool-as-number，并把解析错误包装成 `DesignDslError`。

### 2.10 `src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml`

这是 YAML 版 `QComponent` 基础默认值。

它提供:

```yaml
options:
  pos_x: 0.0um
  pos_y: 0.0um
  orientation: 0.0
  chip: main
  layer: 1
geometry:
  transform:
    translate: ["${options.pos_x}", "${options.pos_y}"]
    rotate: "${options.orientation}"
```

对应原 qlibrary 世界里的 `QComponent` 通用位置、旋转、chip、layer 概念。

### 2.11 `src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml`

这是 YAML 版 `BaseQubit` 的薄层。

它继承 `qcomponent`，增加:

```yaml
options:
  connection_pads: {}
  _default_connection_pads: {}
metadata:
  short_name: Q
merge_rules:
  connection_pads:
    each_entry_extends: _default_connection_pads
    remove_from_resolved_options:
      - _default_connection_pads
```

对应原 `BaseQubit` 里“qubit 有 connection pads，每个 pad 都有一组默认配置”的概念。

### 2.12 `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`

这是 YAML-native `TransmonPocket` 主体。

它继承 `base_qubit`，提供:

- `pad_gap`
- `inductor_width`
- `pad_width`
- `pad_height`
- `pocket_width`
- `pocket_height`
- `_default_connection_pads`

静态 primitives:

```text
pad_top
pad_bot
rect_pk     subtract: true
rect_jj     junction.line
```

generated connection pad primitives:

```text
{pad}_connector_pad
{pad}_wire
{pad}_wire_sub  subtract: true
```

generated pin:

```text
{pad}
```

这里的 `{pad}` 可以是示例里的 `readout`。

## 3. YAML Template Inheritance 如何工作

以 `type: transmon_pocket` 为例。

### 3.1 registry 找模板

`_parse_components()` 看到 component 有 `type`，调用:

```python
expand_component_template(comp_spec, template_registry)
```

`expand_component_template()` 调用:

```python
registry.inheritance_chain("transmon_pocket")
```

返回:

```text
[
  ComponentTemplate(id="qcomponent"),
  ComponentTemplate(id="base_qubit"),
  ComponentTemplate(id="transmon_pocket"),
]
```

### 3.2 parent-first 合并

`component_templates.py` 按 parent-first 顺序合并:

```text
default_options = qcomponent.options
default_options = deep_merge(default_options, base_qubit.options)
default_options = deep_merge(default_options, transmon_pocket.options)
options = deep_merge(default_options, instance_options)
```

metadata 和 geometry 也类似，但 geometry 里的 `primitives`、`pins` 是拼接，不是覆盖。

### 3.3 merge rules

`base_qubit.yaml` 的关键规则:

```yaml
connection_pads:
  each_entry_extends: _default_connection_pads
  remove_from_resolved_options:
    - _default_connection_pads
```

含义:

```yaml
connection_pads:
  readout:
    loc_W: -1
```

会变成:

```yaml
connection_pads:
  readout:
    pad_gap: 15um
    pad_width: 125um
    pad_height: 30um
    pad_cpw_shift: 5um
    pad_cpw_extent: 25um
    cpw_width: cpw_width
    cpw_gap: cpw_gap
    cpw_extend: 100um
    pocket_extent: 5um
    pocket_rise: 65um
    loc_W: -1
    loc_H: +1
```

然后 `_default_connection_pads` 从 resolved options 里移除，避免导出 metadata 里混入内部默认模板。

## 4. Options / Defaults / Merge Rules / Connection Pads 数据流

以 `examples/dsl/transmon_pocket_2q.metal.yaml` 的 Q1 为例:

```yaml
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

数据流:

```text
YAML component spec
  -> expand_component_template()
       qcomponent defaults:
         pos_x, pos_y, orientation, chip, layer, transform
       base_qubit defaults:
         connection_pads, _default_connection_pads, merge_rules
       transmon_pocket defaults:
         pad sizes, pocket sizes, inductor width, default pad options
       instance options:
         pos_x, readout.loc_W/loc_H/cpw_width/cpw_gap
       merge_rules:
         readout = default_connection_pad + readout overrides
  -> _walk_substitute(template_options, ctx)
       "-${vars.qx}" -> "-1.2mm"
       "${vars.cpw_width}" -> "12um"
  -> component_ctx
       options = resolved template_options
       component.name = Q1
       circuit/hamiltonian/netlist visible
  -> _expand_component_generators()
       for_each options.connection_pads
       local pad.key = readout
       local pad.value = resolved readout options
  -> generated operation outputs
       placed.connector_pad
       placed.connector_wire_path
  -> generated primitives/pins
       readout_connector_pad
       readout_wire
       readout_wire_sub
       pin readout
```

关键理解:

- `options` 在 template expansion 后已经是“模板默认值 + 用户覆盖 + connection pad entry defaults”的结果。
- generator 看到的是 resolved options。
- geometry operation 输出不是直接写入 qgeometry，只有被 primitive/pin 引用时才落到 IR。

## 5. Primitive / Pin / QGeometry / Netlist 写到哪里

### 5.1 在 IR 中

`build_ir()` 返回 `DesignIR`。

主要位置:

```text
ir.components
  -> ComponentIR(name="Q1")
     -> primitives: list[PrimitiveIR]
     -> pins: list[PinIR]
     -> type: "transmon_pocket"
     -> options: resolved options
     -> metadata: template metadata
     -> inherited: ["qcomponent", "base_qubit", "transmon_pocket"]

ir.derived
  -> circuit.geometry.Q1.bounds
  -> circuit.geometry.Q1.primitives.*
  -> circuit.geometry.Q1.pins.*
  -> netlist.connections.*
```

### 5.2 在 Metal QDesign 中

`export_ir_to_metal()` 负责写入:

```text
design.components["Q1"]
  -> NativeComponent
  -> metadata["template"]
  -> pins["readout"]

design.qgeometry.tables["poly"]
  -> pad_top, pad_bot, rect_pk, readout_connector_pad

design.qgeometry.tables["path"]
  -> readout_wire, readout_wire_sub

design.qgeometry.tables["junction"]
  -> rect_jj

design.net_info
  -> connect_pins() 生成的 net rows

design.metadata["dsl_chain"]
  -> ir.to_metadata()
```

### 5.3 `metadata/derived` 具体有什么

`_derive()` 计算:

- 每个 component 的整体 bounds。
- 每个 primitive 的 kind、shape、bounds。
- path primitive 的 length。
- 每个 pin 的 points、middle、width、gap、chip。
- 标准化 netlist endpoint。

`export_ir_to_metal()` 成功连接 pins 后，会把 `net_id` 写回 `ir.derived["netlist"]["connections"]`，然后整体放入:

```python
design.metadata["dsl_chain"]
```

所以导出后的 metadata 可以用于汇报和 debug。

## 6. Pins 如何工作

当前支持两种 pin mode。

### 6.1 `tangent_points`

这是普通显式 pin:

```yaml
pins:
  - name: bus
    points: [[0.34mm, -6um], [0.34mm, 6um]]
    width: 12um
```

`_pin_from_spec()` 会:

1. 解析两个点。
2. 检查两点距离是否等于 width。
3. 应用 component/primitive transform。
4. 生成 `PinIR(input_as_norm=False)`。

导出时:

```python
component.add_pin(name, points, width, input_as_norm=False, gap=...)
```

### 6.2 `normal_segment`

这是 connection pad generator 用的模式:

```yaml
pins:
  - name: "${pad.key}"
    mode: normal_segment
    from_operation: placed.connector_wire_path
    segment: last
    width: "${pad.value.cpw_width}"
```

它的含义:

- 从 operation 输出的 LineString 取最后一段作为 pin normal direction。
- `normal_points` 是线段的两个端点。
- `points` 是根据 width 计算出来的 pin 横截面点。
- 导出时 `input_as_norm=True`，把 normal segment 交给 Metal `add_pin()`。

为什么 generated pin 不写 gap:

`transmon_pocket.yaml` 的 generated pin 不显式设置 `gap`，这样 `_pin_from_spec()` 会使用 `width * 0.6`，匹配 qlibrary `QComponent.add_pin()` 默认行为。

## 7. Geometry Operations 如何工作

模板里的 operations 是局部 geometry 计算图。

例子来自 `transmon_pocket.yaml`:

```yaml
connector_wire_path:
  op: polyline
  points:
    - [0um, "${pad.value.pad_cpw_shift + pad.value.cpw_width / 2}"]
    - ["${pad.value.pad_cpw_extent}", "..."]

placed:
  op: transform_group
  sources:
    connector_pad: connector_pad
    connector_wire_path: connector_wire_path
  steps:
    - op: scale
      xfact: "${pad.value.loc_W}"
      yfact: "${pad.value.loc_H}"
    - op: translate
      xoff: "${pad.value.loc_W * options.pad_width / 2}"
```

执行顺序:

1. `evaluate_geometry_operations()` 按 YAML mapping 顺序计算。
2. 每个 operation 的结果放入 `outputs[name]`。
3. 后续 operation 可以 `source: previous_name`。
4. primitive 可以写 `type: path.from_operation` + `operation: placed.connector_wire_path`。
5. pin 可以写 `from_operation: placed.connector_wire_path`。

generator 里还会做 namespace:

```text
connection_pads.readout.connector_wire_path
```

这样多个 pads 不会互相覆盖 operation 名称。

## 8. Circuit / Hamiltonian / Netlist / Geometry 的传播

### 8.1 下行解析顺序

`build_ir()` 里顺序很重要:

```python
vars_table = _optional_mapping(spec, "vars")
ctx_vars = {**vars_table, "vars": vars_table}
circuit = _walk_substitute(..., ctx_vars)
hamiltonian = _walk_substitute(..., {**ctx_vars, "circuit": circuit})
netlist = _walk_substitute(..., {**ctx_vars, "circuit": circuit, "hamiltonian": hamiltonian})
ctx = {**vars_table, "vars": vars_table, "circuit": circuit, "hamiltonian": hamiltonian, "netlist": netlist}
```

所以:

- `circuit` 可以引用 `vars`。
- `hamiltonian` 可以引用 `vars` 和 `circuit`。
- `netlist` 可以引用 `vars`、`circuit`、`hamiltonian`。
- `geometry` 和 templates 可以看到它们。

### 8.2 Design variables 加入模板上下文

为了让默认 `cpw_width` / `cpw_gap` 生效，`build_ir()` 会调用:

```python
_design_variable_context(design_spec, vars_table)
```

它会临时实例化 selected design class，并收集:

```text
design.variables
  + geometry.design.variables
  + root vars
```

这意味着 `build_ir()` 会构造一次 design class。当前已经有测试记录这个行为。

### 8.3 上行 derived 不是物理求解器

当前 `derived` 主要是 geometry/netlist metadata:

- bounds
- path length
- pin points/middle
- normalized endpoint
- export 后的 net_id

它还不是 physics-aware Hamiltonian/circuit derivation。比如它不会从几何自动求 capacitance 或 coupling。这个属于未来 work。

## 9. 和原 qlibrary 的对应关系

| qlibrary 路径 | YAML-native DSL 对应 |
| --- | --- |
| `QComponent.default_options` | `qcomponent.yaml` / component template `options` |
| `QComponent` pos/orientation/chip/layer | `qcomponent.yaml` options + transform |
| `BaseQubit` connection pad handling | `base_qubit.yaml` `connection_pads` + merge rules |
| `TransmonPocket.default_options` | `transmon_pocket.yaml` `options` |
| `TransmonPocket.make()` 画 pad/pocket/junction | `transmon_pocket.yaml` static primitives |
| `make_connection_pad()` | `generators.connection_pads` + geometry operations |
| `add_qgeometry()` | `export_ir_to_metal()` direct `design.qgeometry.add_qgeometry()` |
| `add_pin()` | `export_ir_to_metal()` `NativeComponent.add_pin()` |
| `connect_pins()` | `export_ir_to_metal()` netlist export |

最重要的差异:

原 qlibrary 是“执行 Python class 的 make”。当前 DSL 是“解释 YAML template 并生成 primitive IR”。最终都进入 Metal 的数据表。

## 10. 示例和测试如何对应实现

### 10.1 Primitive chain 示例

文件:

```text
examples/dsl/native_2q_minimal.metal.yaml
examples/dsl/chain_2q_native.metal.yaml
examples/dsl/run_chain_demo.py
```

验证:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

测试:

```text
tests/test_design_dsl.py
```

覆盖:

- schema/root key validation。
- primitive parsing。
- include/extend/for。
- transforms。
- netlist endpoint validation。
- export qgeometry/pins/net_info。
- design variable context behavior。

### 10.2 Template infrastructure

文件:

```text
src/qiskit_metal/toolbox_metal/dsl/template_model.py
src/qiskit_metal/toolbox_metal/dsl/template_registry.py
src/qiskit_metal/toolbox_metal/dsl/component_templates.py
src/qiskit_metal/toolbox_metal/dsl/expression.py
src/qiskit_metal/toolbox_metal/dsl/geometry_ops.py
```

测试:

```text
tests/test_design_dsl_templates.py
```

覆盖:

- template expansion。
- inheritance。
- unknown options rejection。
- expression arithmetic。
- geometry operations。
- normal_segment pins。
- builtin `qcomponent` / `base_qubit` / `transmon_pocket`。
- file-based local template lookup。
- malformed template errors。

### 10.3 TransmonPocket parity

文件:

```text
examples/dsl/transmon_pocket_2q.metal.yaml
examples/dsl/run_transmon_pocket_demo.py
tests/test_design_dsl_transmon_pocket.py
```

验证:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_transmon_pocket.py -q
```

覆盖:

- 两个 YAML-native TransmonPocket 都是 `NativeComponent`。
- qgeometry row names 符合预期。
- generated readout pin 存在。
- netlist 连接成功。
- 与 qlibrary TransmonPocket 参考实现的 geometry/pin parity。

## 11. 当前已知剩余风险和技术债

这里只列当前仍然未解决或 intentionally deferred 的事项; 不把已经修复的 parity gap 作为待办。

1. `build_ir()` 会实例化 selected design class 来读取 design variables。这个行为当前已有测试记录，但未来如果 custom design constructor 有副作用，仍可能需要更轻量的变量读取 API。
2. typed full-string interpolation 的全局语义仍需要进一步文档化和兼容性测试。现在它对 template 很有用，但也可能影响旧 primitive DSL 文件里某些 metadata 的类型形态。
3. `dsl/builder.py` 仍然偏大，混合了加载、schema、primitive parsing、pin parsing、netlist、derived、export 等职责。后续维护更多模板时建议再拆。
4. full Hamiltonian/Circuit semantic propagation 仍是未来工作。当前支持结构化字段、插值和 derived geometry metadata，但还没有 physics-aware defaults、junction symbols、capacitance/coupling derivation。
5. circuit/hamiltonian/geometry/netlist 的一致性和冲突优先级还未定义 strict mode。例如 circuit 里有 Q1，但 geometry 没有 Q1，目前没有完整语义校验。
6. netlist roles、coupling metadata、endpoint reuse policy 还没有进入 schema。当前 `netlist.connections` 只接受 `{from, to}`，且 endpoint reuse 会被拒绝。
7. metadata/provenance 还没有拆成 raw/resolved/generated/derived/export 多层结构。现在 `design.metadata["dsl_chain"]` 已经可用，但未来 round-trip/debug 会需要更细粒度来源信息。
8. renderer/qgeometry table compatibility strategy 仍然 intentionally deferred。当前导出直接写 `design.qgeometry.add_qgeometry()`，测试也确认不会注入 renderer defaults。
9. template package/discovery/versioning 仍然很轻量。当前支持 inline、builtin、本地文件; 未来多个 YAML qlibrary equivalents 可能需要版本和依赖机制。
10. primitives/pins 的 list override 粒度还比较粗。未来如果需要覆盖 parent template 中单个 primitive，可能需要 map keyed by name 再 lower 到 list。

已修复、不要再作为待办讲:

- `connection_pads.each_entry_extends` 未生效。
- generator 被接受但静默忽略。
- falsey metadata 被接受。
- 非直角 transform 下 `normal_segment` pin IR/export 不一致。
- generated TransmonPocket pin gap 使用 `cpw_gap` 而不是 `0.6 * width`。
- 默认 `cpw_width/cpw_gap` 无法从 selected design variables 解析。
- 缺少两 qubit TransmonPocket 示例、demo、parity tests。
- 表达式 runtime error 和 bool-as-number 的错误契约问题。

## 12. 推荐阅读顺序

如果你只有 20 分钟:

1. `examples/dsl/transmon_pocket_2q.metal.yaml`
2. `examples/dsl/run_transmon_pocket_demo.py`
3. `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`
4. `src/qiskit_metal/toolbox_metal/dsl/builder.py` 里的 `build_ir()` 和 `export_ir_to_metal()`
5. `tests/test_design_dsl_transmon_pocket.py`

如果你有 1 小时:

1. 先跑 `run_chain_demo.py` 和 `run_transmon_pocket_demo.py`。
2. 读 `examples/dsl/README.md`。
3. 读 `design_dsl.py`，确认它只是 facade。
4. 读 `builder.py` 的数据类: `PrimitiveIR`、`PinIR`、`ComponentIR`、`DesignIR`、`NativeComponent`。
5. 读 `build_ir()`，只跟一条路径，不展开所有 helper。
6. 读 `_parse_components()`，看 template expansion、operations、generators、primitive/pin 解析怎么串起来。
7. 读 `component_templates.py`，理解 options merge。
8. 读三个 YAML templates: `qcomponent`、`base_qubit`、`transmon_pocket`。
9. 读 `geometry_ops.py`，重点看 `transform_group`。
10. 最后读 `tests/test_design_dsl_transmon_pocket.py`，确认 parity 依据。

如果你要准备答辩:

1. 先背熟这条路径:

```text
build_design -> build_ir -> template expansion -> primitive IR -> export_ir_to_metal
```

2. 再能说清四个“写到哪里”:

```text
qgeometry rows -> design.qgeometry.tables
pins           -> design.components[name].pins
netlist        -> design.net_info
chain metadata -> design.metadata["dsl_chain"]
```

3. 最后能回答一个边界问题:

“没有删除 Metal core，只是移除了 qlibrary Python class 作为 DSL authoring/build target。”

## 13. 本次重新验证结果

已在目标 worktree 下重新运行:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

结果:

```text
pytest:
121 passed, 8 warnings in 10.01s

run_chain_demo.py:
PASS: native DSL chain exported to Metal

run_transmon_pocket_demo.py:
PASS: YAML-native TransmonPocket template exported to Metal
```

