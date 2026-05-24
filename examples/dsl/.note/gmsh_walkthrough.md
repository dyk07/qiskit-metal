# DSL → Gmsh 适配器 走读 (M1 + M3 + M4 + M5)

适用 worktree: `D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

> 本文档伴随 `.claude/scratch/gmsh-interface/02_plan.md`。
> §1 — YAML schema (M1); §2 — IR 字段; §3 — physical group 命名 (M3);
> §4 — demo 命令 (M3); §5 — mesh kwarg 单位 + 防呆 (M3/M5);
> §6 — 端口 / 对称面 / endcap (M4); §7 — chip.size 与 ground bbox 语义差
> 异 (M5); §8 — `subtract=True` primitive 在 fragment 后不入 group (M5);
> §9 — chip layer 与 layer_stack 的约束 (M5)。

---

## 1. YAML schema: `simulation.gmsh`

DSL v3 顶层增加一个可选段 `simulation:`, 用来承载 "怎么把同一份几何送给某个仿真器" 的元数据。第一个被支持的目标是 `gmsh` (本地 OCC + mesh)。该段不影响 `build_design()` 的行为, 旧 YAML 不写 `simulation:` 时, `DesignIR.simulation == {}`, 上层链路 100% 向后兼容。

```yaml
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um, z: 0um, material: pec}
      3: {kind: dielectric, thickness: -750um, z: 0um, material: silicon, eps_r: 11.45}
    airbox:
      top: 890um            # 真空盒上半部高度
      bottom: 1650um        # 真空盒下半部高度
      side_buffer: 200um    # chip bbox 向四周扩张的余量
    ports:
      - {pin: Q1.bus, type: lumped, impedance: 50ohm, value: 1.0}
      - {pin: Q2.bus, type: ground}
    symmetry:
      - {plane: y0, condition: pec}
    mesh:
      max_size: 70um
      min_size: 5um
      max_size_jj: 5um
      conductor_refine: {min_dist: 10um, max_dist: 130um}
    output: {format: msh4, scaling: 1.0}
```

### 1.1 单位约定

所有长度字面量在 IR 里 **解析为 mm float**, 和 `PrimitiveIR.geometry` / `PinIR.width` 单位保持一致。adapter 入口处会一次性 `× 1e-3` 转 SI。这样:
- 上层 YAML 用什么单位写 (`12um` / `0.012mm` / `1.2e-5m`) 都行, pint 负责换算。
- IR 中数值统一为 mm float, 既方便和现有 IR 字段比对, 又规避了 IR 内部多套单位。
- adapter 内部统一 SI, 下游求解器拿到 `.msh` 不会因 mm/m 混用导致 ε0 量级错乱。

例: `thickness: 2um` 进 IR 后是 `0.002` (mm), `thickness: -750um` 是 `-0.75` (mm)。

### 1.2 layer_stack 条目

每个 key 必须是 int (layer id)。条目允许的字段:

| 字段 | 必填 | 说明 |
|---|---|---|
| `kind` | 是 | `metal` 或 `dielectric` |
| `thickness` | 是 | 非零 mm float; 负值表示 dielectric 向 -z 方向展开。`0` 会触发 schema error (退化 extrude) |
| `z` | 否 | layer 的 z 中心, 默认 `0um` |
| `material` | 否 | 字符串标签, 例 `pec` / `silicon` (供 adapter / 求解器分辨) |
| `eps_r` | 否 | 相对介电常数 (dielectric) |
| `tan_delta` | 否 | 损耗角正切 |

**stack 层级硬约束** (plan §0 + §10):
- `simulation.gmsh` 段一旦出现, `layer_stack` 必填; 缺省或空 dict 都报错。
- stack 至少含一个 `kind=metal` layer (没有金属层 adapter 无法 extrude ground)。
- stack 必须覆盖所有 `geometry.components[*].primitives[*].layer` 引用。整段 `simulation:` 不写时不校验, 由 adapter 用默认 stack 兜底。

### 1.3 airbox

`top / bottom / side_buffer` 默认值在 adapter 端给出 (`{top: 890um, bottom: 1650um, side_buffer: 200um}`, 与 `LayerStackHandler` / `MultiPlanar._uwave_package` 默认对齐)。IR 层不补默认, 缺省字段时 `simulation.gmsh.airbox` 字典中相应 key 也缺省。

### 1.4 ports

`pin` 必须是 `"<component_name>.<pin_name>"`, 由 `.` 拆分 (`rsplit(".", 1)`)。

- `type`: `lumped` (默认) 或 `ground`
- `impedance`: 接受 `50ohm` / `50` (单位仅允许 `ohm`/`ohms` 及大小写变体, 或无单位)
- `value`: 接受 bare number (驱动电压/电流幅度)

同一个 `(component, pin)` 不能被两个端口同时引用。

### 1.5 symmetry

可选, 0 个或多个对称面。

- `plane`: `x0` / `y0` / `z0`
- `condition`: `pec` (默认) 或 `pmc`

同一 plane 不能重复声明。

### 1.6 mesh

- `max_size` / `min_size` / `max_size_jj`: 必须 > 0 (mm float)
- `conductor_refine.min_dist` / `conductor_refine.max_dist`: 用于 Distance + Threshold field

### 1.7 output

- `format`: 字符串, 例 `msh4`
- `scaling`: bare number; 默认 `1.0`, 表示 `.msh` 文件坐标也是 SI 米

---

## 2. 在 build_ir 里的接入位置

`_parse_simulation()` 在 `build_ir()` 的最后阶段被调用 (在 `derived` 计算完之后), 让端口 / netlist 引用可以借助现有的 component / pin 列表做校验。

```python
simulation_ctx = {**ctx, "derived": derived}
simulation = _parse_simulation(spec.get("simulation"), simulation_ctx,
                               variable_context, components)
```

`_walk_substitute` 在 `_parse_simulation` 内部对整段执行一次, 让 `${...}` 表达式 (`${vars.air_top}` 之类) 像其它段一样被解析。

---

## 3. Physical group 命名约定 (M3)

`assign_physical_groups` 在 fragment 之后注册全部 physical group。名称由
`_gmsh_physical.PHYSICAL_GROUP_NAMING` 字典模板生成, 并经 `_sanitize` 满足
plan §6 硬约束 (`^[A-Za-z][A-Za-z0-9_]*$`)。

### 3.1 命名模板表

| 类型 | 模板 | dim | 来源字段 |
|---|---|---|---|
| metal layer ground 体 | `gnd_layer{layer}` | 3 | `tracker.layer_ground[layer]` |
| metal layer ground 外表面 | `gnd_layer{layer}_sfs` | 2 | `getBoundary(layer_ground)` |
| dielectric layer 体 | `substrate_layer{layer}` | 3 | `tracker.layer_ground[layer]` (kind=dielectric) |
| component poly/path 体 | `{component}_{primitive}` | 3 | `tracker.polys` / `tracker.paths` |
| component poly/path 外表面 | `{component}_{primitive}_sfs` | 2 | `getBoundary(component_volume)` |
| junction surface | `{component}_{primitive}` | 2 | `tracker.juncs` |
| 真空体 | `vacuum` | 3 | `tracker.vacuum_box` |
| 真空外边界 | `vacuum_outer` | 2 | `getBoundary(vacuum_box)` |
| 端口面 (lumped, M4) | `port_{component}_{pin}` | 2 | `tracker.ports` |
| 端口面 (ground, M4) | `port_{component}_{pin}_gnd` | 2 | (type=ground) |
| 对称面 (M4) | `symmetry_{plane}` | 2 | `tracker.symmetry_surfaces` |

M3 实现已注册前 8 行 (含 dielectric)。port / symmetry 模板已在 `PHYSICAL_GROUP_NAMING` 占位, M4 直接复用而无需改命名层。

### 3.2 sanitize 规则

`_sanitize(name)` 把任意字符串改成合法 gmsh 标识符:

1. 非 `[A-Za-z0-9_]` 字符 (`.` / `-` / 空格 / 全角字符等) → `_`
2. 数字开头 → 前缀 `g_`
3. 空串 → `unnamed`

例: `Q1.bus.pad_left` → `Q1_bus_pad_left`; `2um_pad` → `g_2um_pad`。命名表
里的模板字段 (`{component}` / `{primitive}` / `{pin}` / `{layer}`) 应在
sanitize 之前展开, 整名再走 sanitize。

### 3.3 唯一性硬约束

`_GroupRegistry` 维护已分配名集合, **重名直接 raise**:

```
ValueError: physical group name 'Q1_pad_left' reused (already assigned with dim=3)
```

不静默叠加 — 这通常意味着 IR 里有同名 primitive (例: 两个 component 同名同 primitive)。一个 dimtag 可以属于多个 physical group (例: M4 的端口面同时是 ground layer 表面), 这是 gmsh 允许的, 由 `_gmsh_physical.py` 在不同 *名称* 上注册即可。

---

## 4. 跑 demo 与查看 mesh (M3)

完整流水线脚本: `examples/dsl/run_chain_gmsh_demo.py`。它绕过 `QDesign` 与 `QGmshRenderer`, 直接调 `build_mesh()`。

### 4.1 常用命令

```powershell
# 只跑流水线, 不写文件 (默认粗 mesh, ~6 秒)
C:\ProgramData\anaconda3\envs\metal-env\python.exe `
    examples\dsl\run_chain_gmsh_demo.py

# 写出 msh4
C:\ProgramData\anaconda3\envs\metal-env\python.exe `
    examples\dsl\run_chain_gmsh_demo.py --output build\chain_2q.msh

# 打开 Gmsh GUI 看几何 / 物理组划分
C:\ProgramData\anaconda3\envs\metal-env\python.exe `
    examples\dsl\run_chain_gmsh_demo.py --gui

# 用 YAML 自带细 mesh 设置 (生成 ~130MB; 验真才用, 别 CI 跑)
C:\ProgramData\anaconda3\envs\metal-env\python.exe `
    examples\dsl\run_chain_gmsh_demo.py --output build\fine.msh --fine
```

### 4.2 期望输出

`chain_2q_native.metal.yaml` 默认跑出 17 个 physical groups, 含 plan §11 完工标准点名的 6 个关键 group:

```
schema           : qiskit-metal/design-dsl/3
components       : ['Q1', 'Q2', 'bus']
bounding_box (m) : xmin=-0.0018, ymin=-0.00046, xmax=0.0018, ymax=0.00046
physical groups  : 17
  - Q1_jj (dim=2, n_tags=1)
  - Q1_pad_left (dim=3, n_tags=2)        # fragment 后被切碎成 2 块, OCC 正常行为
  - Q1_pad_left_sfs (dim=2, n_tags=11)
  - ...
  - gnd_layer1 (dim=3, n_tags=1)
  - substrate_layer3 (dim=3, n_tags=1)
  - vacuum (dim=3, n_tags=1)
  - vacuum_outer (dim=2, n_tags=60)
PASS: native DSL chain meshed via gmsh_adapter
```

`bounding_box_m` 只覆盖 XY 平面 (4 元 `(xmin, ymin, xmax, ymax)`); z 范围 = `(-options.airbox["bottom"], +options.airbox["top"])`, 调用方按需从 `result.options.airbox` 取。

### 4.3 GUI 看物理组

`--gui` 走 `gmsh.fltk.run()`。在 Tools → Visibility → Physical groups 里可以按名称 toggle 显示每一组体 / 面。这是验真物理组划分最直观的路径。

---

## 5. Mesh kwarg 与单位 (M3 踩坑落字)

`build_mesh(yaml, options={...})` 的 `options` kwarg 与 YAML `simulation.gmsh` 走 **同一套 schema** (在 r1 后 schema-aware merge, 见 `02_plan.md §0.3` + `gmsh_adapter._normalize_options`)。

### 5.1 长度单位约定 — 全部 mm float

```python
# 正确: mm 单位 (与 IR 内部 / YAML 字面量解析后的语义一致)
build_mesh(yaml, options={"mesh": {"max_size": 2.0,        # 2 mm
                                    "min_size": 0.5,       # 500 um
                                    "max_size_jj": 0.5,
                                    "conductor_refine": {"min_dist": 1.0,
                                                          "max_dist": 3.0}}})

# 也可以只覆盖 layer_stack 的一项, 其它字段从 IR 继承:
build_mesh(yaml, options={"layer_stack": {1: {"kind": "metal",
                                              "thickness": 0.005,   # 5 um
                                              "z": 0.0,
                                              "material": "pec"}}})
```

adapter 入口处 `_normalize_options` 一次性 `× 1e-3` 转 SI; 内部 / `.msh` 文件输出 / gmsh 选项 (`Mesh.MeshSizeMin/Max`) 全部 SI 米。

### 5.2 不要传 SI 米

`options={"mesh": {"max_size": 0.001}}` 会被当成 0.001 **mm = 1um**, 之后还会再 `× 1e-3` 转 SI = **1 nm**。结果是 mesh size field 在 ~mm 量级的 chip 上要划出 ~10^18 个单元, gmsh.generate(3) 卡死并把内存涨到 10GB+。**这是一条契约, 不是 bug**: kwarg 与 IR 字段同语义, 都是 mm。

**M5 防呆 (`_check_mesh_length_mm`)**: 任何 mesh kwarg 长度 (`max_size` / `min_size` / `max_size_jj` / `conductor_refine.{min_dist, max_dist}`) 落在 `[1e-5, 100]` mm 范围之外 (即 < 10 nm 或 > 10 cm) 时直接 `ValueError`, 提示 "outside the sane range"。这条范围是经验值: 10 nm 比单原子还细, 10 cm 比典型 chip 还大, 都视作单位误用。若真有合理需求超出此范围, 改进 `_MESH_LENGTH_MIN_MM` / `_MESH_LENGTH_MAX_MM` 常量。

### 5.3 部分覆盖 (kwarg 只补缺)

`options` 是 *shallow override*: 它的 key (如 `mesh`) 整体替换 IR 同 key 的值, **不是嵌套深 merge**。例如想保留 YAML 中的 `mesh.conductor_refine` 同时只改 `mesh.max_size`, 应该把整个 `mesh` 块写全。这与 reviewer §2.1 的 schema-aware 校验路径一致 (走 `_parse_gmsh_simulation` 整段重过)。

---

## 6. 端口 / 对称面 / open-pin endcap (M4 + M5)

### 6.1 流水线位置

`build_mesh` 在 stage A→B (component primitive 渲染) 之后插入了三个 M4 子阶段:

- **Stage B'** (`_stage_endcaps_and_ports`): 遍历 IR 推断 open pins (`compute_open_pins` 从 `derived.netlist.connections` 推算 — 未出现在 connection 里的 pin 即 open); 端口 pin 强制加 endcap (无论是否 connected — 用户显式声明端口的意图压倒 open/connected 推断)。每个目标 pin 画一个 endcap box (`addBox`), 同时记 `_PortBoxSpec` (box bbox + pin 法向 + 顶部 z) 到 `tracker.port_box_specs`。端口元数据 (`{component, pin, is_lumped}`) 写进 `tracker.port_metadata` 给 stage F 命名用。
- **Stage C'** (`apply_symmetry_cuts`): 按 `simulation.gmsh.symmetry` 切掉对称面外侧的半空间。支持 `x0` / `y0` / `z0` 三个平面; `condition: pec` 或 `pmc` 当前是 *元数据标记*, 求解器接入时再消费。**顺序约束**: symmetry 必须在 stage E (fragment) 之前完成, 否则切面没法和邻接 volume 缝合。
- **Stage D'** (`resolve_port_surfaces`, M5 移到 stage D 之后 / stage E fragment 之前): cut 之后, 从 ground 缺口边界面里筛出端口面, 替换 `tracker.port_box_specs` 为真实 face tags 写进 `tracker.ports`。fragment 把 `tracker.ports` 也当 input, 让 face tag 在共享拓扑下走正常 remap (M4 r1 观察 #2)。

### 6.2 lumped port 面的语义 (M5 收紧)

M4 r1 观察 #1 + M5 修: lumped port 面 = endcap box 的 **单一垂直壁** (法向 = +pin_normal, 即远离 trace 的那一侧)。这是 EM lumped port 的标准位置 — 端口面应垂直于电流流向, 让求解器读端口电压时不需要再积分多面。

`_PortBoxSpec.top_z_si` 是为未来 box 顶面独立 face 设计预留的字段, 当前不参与筛选; `pin_normal_xy` 是 pin 几何的右手法线 (与 `add_endcaps:669` 的 `normal` 字段同义), 指向 chip 外侧。

测试 `test_m4_lumped_port_surface_exists` 断 `len(tags) == 1` — 端口面恰好一面。若未来 design 触发 box 几何变形 (例如 cut 与 fragment 后端口壁被切碎), 这条断言会暴露。

### 6.3 命名约定

- `type: lumped` → `port_{component}_{pin}` (例 `port_Q1_bus`)
- `type: ground` → `port_{component}_{pin}_gnd` (例 `port_Q1_bus_gnd`)
- 对称面 → `symmetry_{plane}` (例 `symmetry_y0` / `symmetry_x0` / `symmetry_z0`)

端口面命名不带 `net_id`: net_id 是 layout 期产物, 端口是 EM 期产物, 语义不同。

### 6.4 nit 4.3 — symmetry cut 与 endcap_subtracts 的相互作用 (M5 won't fix)

理论上 `apply_symmetry_cuts` 应把 endcap_subtracts 也当 cut target, 让跨对称面的 endcap box 提前一分为二, 避免 stage D 用整 box 旧 tag 引用 OCC 已经局部失效的拓扑。M5 实验显示这条做法会触发 OCC 把 ground / vacuum 视作 fragment 处理 (target 间相互重叠拓扑被 OCC 当 cut 边界), 把 ground 切成多块 + 后续 fragment 拿到无效 tag。**当前不修**, 依赖 OCC `cut(ground_half, full_box)` 在 stage D 自动取交集。复杂 design (e.g. 端口 box 跨对称面) 若暴露问题, 需要重新设计 symmetry-aware 的 endcap 渲染路径。

---

## 7. `chip.size` 与 ground bbox 的语义差异 (M5)

DSL 的 `geometry.design.chip.size` (e.g. `4mm x 4mm`) 是 *layout 信息*, **不会** 被 gmsh adapter 直接消费为 ground / vacuum 几何尺寸:

- adapter 自己算 chip XY bbox (`compute_chip_bbox_si`): 遍历所有 `PrimitiveIR.geometry.bounds` 取 union, 再加 `simulation.gmsh.airbox.side_buffer`。这是 ground / vacuum 在 XY 平面的真实覆盖范围。
- `chip.size` 在 adapter 路径上**不参与**任何几何计算 — 它只在 IR + `build_design` 路径中给 QDesign 设置 `chip.main.size_x/y` 元数据。

后果:
- 一份只放小 component 在大 chip 上的 YAML, ground bbox 会贴着 component 而不是贴 chip.size; 这与 `QGmshRenderer` 用 `LayerStackHandler.gather_chip_bounds` 拿 chip.size 的行为不同。下游求解器若期待 ground 跨整片 chip, 需要在 YAML 里加占用整片 chip 的 dummy ground primitive 或调大 `side_buffer`。
- 反过来, 若 component 排布超出了 `chip.size`, adapter 仍会按实际 bounds 出 ground; 这种 inconsistency 应该在 layout 阶段就规整。

未来若有需求, 可以加 `simulation.gmsh.ground_bbox: chip_size | auto` 显式开关 — 当前 plan 不引入。

---

## 8. `subtract=True` primitive 在 fragment 后不留命名 (M5)

`PrimitiveIR.subtract: true` 表示该 primitive 体积要从 ground 里 cut 掉 (而不是当 conductor 加进去)。在 gmsh adapter 里:

1. Stage A/B 把它们渲染成 OCC volume, 但**不**进 `tracker.polys / tracker.paths`; 而是写到 `tracker.subtracts[layer]`。
2. Stage D (`apply_cuts`) 把 subtracts 从 ground 里 cut 掉; cut 之后 OCC 自动消耗这些 volume tag, tracker 清空 `subtracts.clear()`。
3. Stage F (`assign_physical_groups`) 遍历 `tracker.polys / paths / juncs` 出命名 group — `subtracts` 不在这个集合, 因此 `subtract=True` 的 primitive **不会** 出现在 `result.physical_groups` 里。

下游求解器若想给某个 "凹陷" 单独标签, 需要把它从 `subtract=True` 改为正常的 `subtract=False` poly + 一个相邻的 cut helper — 或直接添加新 primitive 用 `subtract=False` 标 conductor / dielectric / 端口面。

---

## 9. chip layer ⊆ layer_stack (M5)

`PrimitiveIR.layer` 引用的 layer id 必须出现在 `simulation.gmsh.layer_stack` 里。M1 schema 校验在 `_parse_gmsh_simulation` 里强制:

- 若 IR 中有 primitive 引用 `layer=N` 但 `layer_stack` 不含 N → `DesignDslError` (`missing layer N referenced by primitives`)
- 若 `layer_stack` 缺 metal layer (没有 `kind: metal`) → 拒
- 若 `thickness == 0` → 拒 (extrude 退化)

这条约束既在 build_ir 时校验, 也在 `gmsh_adapter._normalize_options` 走 kwarg 路径时**整段重过** `_parse_gmsh_simulation` — kwarg 不能绕开硬性前提。

未声明在 stack 里但只在 IR 中存在的 layer 会让 `render_component` 的 `layer_stack_si[layer]` lookup 报 KeyError; M1 schema 验证比这条 lookup 早, 把错误信息明示出来。

---

物理 group 命名约定 (上 §3 + §6) 同时也是下游求解器的契约, 改命名前需要 ping 下游同步。M4 端口面命名 (`port_{component}_{pin}`) 与 M5 端口面单顶面收紧 (`len(tags) == 1`) 是这条契约里两条加固。
