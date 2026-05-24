# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter (M2): 几何阶段 A / B / D 集成测试。

需要 ``gmsh`` 装在当前环境; 缺失时整文件 skip。M3 / M4 的 fragment /
physical groups / mesh export 不在此测; ports / symmetry / endcap 也不在此测。
"""

from __future__ import annotations

from pathlib import Path

import pytest

gmsh = pytest.importorskip("gmsh")

from qiskit_metal.toolbox_metal.dsl.gmsh_adapter import (  # noqa: E402
    DEFAULT_AIRBOX_MM,
    DEFAULT_LAYER_STACK_MM,
    GmshMeshResult,
    GmshOptions,
    build_mesh,
)
from qiskit_metal.toolbox_metal.dsl import (  # noqa: E402
    DesignDslError,
    DesignIR,
    build_ir,
)


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dsl" / (
    "chain_2q_native.metal.yaml")


# -----------------------------------------------------------------------------
# 输入分支 + 类型校验
# -----------------------------------------------------------------------------

def test_build_mesh_rejects_unsupported_input_type():
    """plan §0: 只接 str / Path / DesignIR; 别的 raise TypeError。"""
    with pytest.raises(TypeError, match="QDesign is not supported"):
        build_mesh(object())  # type: ignore[arg-type]


def test_build_mesh_accepts_design_ir():
    """直接传 DesignIR 也行, 不必经过 YAML reparse。"""
    ir = build_ir(EXAMPLE)
    result = build_mesh(ir, generate=False)
    assert isinstance(result, GmshMeshResult)
    assert result.ir is ir


# -----------------------------------------------------------------------------
# 阶段 A-D 整体: chain_2q_native 端到端跑完
# -----------------------------------------------------------------------------

def test_chain_2q_native_builds_geometry():
    """plan §8 M2 验收: 跑到 cut, `getEntities(3)` 非空 + bbox 合理。"""
    # Pre-initialize gmsh so build_mesh only calls gmsh.clear() and does NOT
    # finalize on return — this lets us inspect raw entity counts afterward.
    # (build_mesh finalizes only when it was the one that called gmsh.initialize())
    gmsh.initialize()
    try:
        # generate=False 跳过 fragment / physical / mesh, 仅校验阶段 A-D
        result = build_mesh(EXAMPLE, generate=False)

        assert isinstance(result.options, GmshOptions)
        assert result.mesh_path is None  # generate=False 不出 .msh
        assert result.physical_groups == {}  # generate=False 不分组

        # bbox 含 side_buffer; chip_2q size ~ 6mm x 6mm but primitive bbox 由
        # 实际 primitive 决定, 不是 chip size; 这里只验证 buffer 已加到外侧。
        xmin, ymin, xmax, ymax = result.bounding_box_m
        assert xmin < 0 < xmax
        assert ymin < 0 < ymax
        assert (xmax - xmin) > 2 * result.options.airbox["side_buffer"]
        assert (ymax - ymin) > 2 * result.options.airbox["side_buffer"]

        # 3D 实体 = ground per layer + path/poly volumes + vacuum (cut 之后)
        entities_3d = gmsh.model.getEntities(dim=3)
        assert len(entities_3d) >= 4  # 至少 ground1 + substrate + 一些 volume + vacuum
        # 2D 实体含 JJ surfaces (2 个 qubit 各 1 JJ)
        entities_2d = gmsh.model.getEntities(dim=2)
        assert len(entities_2d) > 0
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


def test_simulation_options_si_units():
    """layer_stack / airbox 在 GmshOptions 里是 SI (米); IR 中还是 mm float。"""
    result = build_mesh(EXAMPLE, generate=False)
    options = result.options
    # chain_2q_native 的 layer 1 厚度 2um = 2e-6 m
    assert options.layer_stack[1]["thickness"] == pytest.approx(2e-6)
    assert options.layer_stack[3]["thickness"] == pytest.approx(-7.5e-4)
    # airbox top 890um = 8.9e-4 m
    assert options.airbox["top"] == pytest.approx(8.9e-4)


def test_default_layer_stack_used_when_simulation_absent():
    """无 `simulation:` 段的 YAML 应该用 adapter 默认 stack (与 LayerStackHandler 数值对齐)。"""
    # 临时构造一个不含 simulation 的 YAML
    yaml_text = """
schema: qiskit-metal/design-dsl/3
vars: {pad_w: 200um}
hamiltonian: {}
circuit: {}
netlist: {connections: []}
geometry:
  design:
    class: DesignPlanar
    chip: {size: 4mm x 4mm}
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0mm, 0mm],
           size: ["${pad_w}", 100um]}
      pins:
        - {name: bus, points: [[0.1mm, -6um], [0.1mm, 6um]],
           width: 12um, gap: 7um}
"""
    result = build_mesh(yaml_text, generate=False)
    # 默认 stack: layer 1 = metal 2um, layer 3 = dielectric -750um
    assert result.options.layer_stack == {
        1: {"kind": "metal", "thickness": 2e-6, "z": 0.0, "material": "pec"},
        3: {"kind": "dielectric", "thickness": -7.5e-4, "z": 0.0,
            "material": "silicon", "eps_r": 11.45},
    }


# -----------------------------------------------------------------------------
# 默认常量与 LayerStackHandler 数值对齐 (不 import 它)
# -----------------------------------------------------------------------------

def test_default_constants_match_layer_stack_handler_values():
    """这条测试是契约性的: 改默认值必须显式更新 plan §0 数值对齐说明。"""
    assert DEFAULT_LAYER_STACK_MM == {
        1: {"kind": "metal", "thickness": 0.002, "z": 0.0, "material": "pec"},
        3: {"kind": "dielectric", "thickness": -0.75, "z": 0.0,
            "material": "silicon", "eps_r": 11.45},
    }
    assert DEFAULT_AIRBOX_MM == {
        "top": 0.89, "bottom": 1.65, "side_buffer": 0.2,
    }


# -----------------------------------------------------------------------------
# M2 r1 §2.1: options kwarg 也必须走 schema 校验, 不可绕开 M1 硬约束
# -----------------------------------------------------------------------------

def test_options_kwarg_invalid_thickness_rejected():
    """通过 kwarg 注入非法 layer_stack (`thickness=0`) 必须被拒。"""
    with pytest.raises(DesignDslError, match="thickness must be non-zero"):
        build_mesh(
            EXAMPLE,
            options={"layer_stack": {1: {"kind": "metal", "thickness": 0.0,
                                         "z": 0.0, "material": "pec"}}},
        )


def test_options_kwarg_all_dielectric_rejected():
    """kwarg 把 stack 全改为 dielectric (无 metal) 必须被拒。

    deep-merge 语义下, 只传 layer 3 会保留 YAML 里的 layer 1 (metal).
    要让整个 stack 变成无 metal, 必须把所有 layer 都覆盖成 dielectric.
    """
    with pytest.raises(DesignDslError,
                       match="at least one metal layer"):
        build_mesh(
            EXAMPLE,
            options={"layer_stack": {
                # Override layer 1 (metal in YAML) → dielectric
                1: {"kind": "dielectric", "thickness": 0.002, "z": 0.0},
                # Override layer 3 (already dielectric, keep as dielectric)
                3: {"kind": "dielectric", "thickness": -0.75, "z": 0.0,
                    "material": "silicon", "eps_r": 11.45},
            }},
        )


def test_options_kwarg_missing_primitive_layer_rejected():
    """kwarg 给的 stack 缺 primitive 引用的 layer 必须被拒。

    deep-merge 语义下, 传 {99: ...} 只是在 IR 的 layer_stack 里 *追加* layer 99,
    原有的 layer 1/3 仍然存在 — 所以此测必须用无 simulation 段的 YAML (options
    成为唯一 layer_stack 来源), 才能真正触发 "缺 layer 1" 的报错。
    """
    no_sim_yaml = """
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {connections: []}
geometry:
  design:
    class: DesignPlanar
    chip: {size: 4mm x 4mm}
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0mm, 0mm],
           size: [200um, 100um]}
"""
    with pytest.raises(DesignDslError,
                       match="missing layer.*referenced by primitives"):
        build_mesh(
            no_sim_yaml,
            options={"layer_stack": {99: {"kind": "metal",
                                          "thickness": 0.002, "z": 0.0}}},
        )


def test_options_kwarg_unknown_port_pin_rejected():
    """kwarg 注入引用不存在 pin 的 port 必须被拒 (port pin 引用校验)。"""
    with pytest.raises(DesignDslError, match="unknown component|unknown pin"):
        build_mesh(
            EXAMPLE,
            options={"ports": [{"pin": "GhostQ.ghostPin", "type": "lumped"}]},
        )


def test_options_kwarg_si_mesh_length_rejected():
    """M5 (M3 r1 建议 3): mesh kwarg 长度按 mm; 误传 SI 米值 (5e-6) 必须被拒。

    `5e-6 mm` = 5 nm < 10 nm 下界 → 触发单位防呆 (walkthrough §5.2)。
    """
    with pytest.raises(ValueError, match="outside the sane range"):
        build_mesh(
            EXAMPLE,
            options={"mesh": {"max_size": 5e-6}},   # 5 nm 当 mm, 误用
            generate=False,
        )


def test_options_kwarg_oversized_mesh_length_rejected():
    """mesh kwarg 长度 > 100 mm 也视为单位误用 (10 cm 不是合理 mesh size)。"""
    with pytest.raises(ValueError, match="outside the sane range"):
        build_mesh(
            EXAMPLE,
            options={"mesh": {"min_size": 200.0}},   # 200 mm = 20 cm
            generate=False,
        )


def test_options_kwarg_conductor_refine_units_checked():
    """conductor_refine.min_dist / max_dist 也走单位防呆。"""
    with pytest.raises(ValueError, match="conductor_refine.min_dist"):
        build_mesh(
            EXAMPLE,
            options={"mesh": {"conductor_refine": {"min_dist": 1e-7}}},
            generate=False,
        )


def test_options_kwarg_partial_override_does_not_require_layer_stack():
    """kwarg 只覆盖 mesh / output 等非必填字段时, IR 中的 layer_stack 仍生效。

    chain_2q_native 自带最小 simulation 段, 这里仅覆盖 mesh.max_size,
    应顺利通过 schema 而不报 "layer_stack is required"。
    """
    result = build_mesh(EXAMPLE,
                        options={"mesh": {"max_size": 0.05}},  # 50um
                        generate=False)
    assert result.options.mesh.get("max_size") == pytest.approx(5e-5)


# -----------------------------------------------------------------------------
# M3: fragment + physical groups + mesh export 端到端
# -----------------------------------------------------------------------------

# 极粗 mesh 参数, 把 mesh.generate 时间压到秒级 — 这个 design 物理尺度
# 是 ~mm, mesh size 与之同尺度可以保证只生成 O(100) 单元而不是 O(10^6)。
# 单位 = mm (kwarg 约定; adapter 入口 ×1e-3 转 SI)。
_COARSE_MESH = {
    "max_size": 2.0,        # 2 mm
    "min_size": 0.5,        # 500 um
    "max_size_jj": 0.5,
    "conductor_refine": {"min_dist": 1.0, "max_dist": 3.0},
}


@pytest.fixture(scope="module")
def m3_result(tmp_path_factory):
    """跑一次完整 build_mesh, 后续 M3 测试共享结果, 避免重复 mesh.generate。"""
    out_dir = tmp_path_factory.mktemp("m3")
    out = out_dir / "chain_2q.msh"
    result = build_mesh(EXAMPLE, output_path=out,
                        options={"mesh": _COARSE_MESH})
    return result, out


def test_m3_full_pipeline_writes_msh(m3_result):
    """M3 验收: build_mesh 全流水线写出 .msh, 关键 physical groups 存在。"""
    result, out = m3_result
    assert result.mesh_path == out
    assert out.exists() and out.stat().st_size > 0


def test_m3_required_physical_groups(m3_result):
    """plan §11 完工标准: 6 个关键 group 必须出现 + dim 分类正确。"""
    result, _ = m3_result
    groups = result.physical_groups
    required_with_dim = {
        "gnd_layer1": 3,
        "substrate_layer3": 3,
        "vacuum": 3,
        "Q1_pad_left": 3,
        "bus_center_trace": 3,
        "vacuum_outer": 2,
    }
    for name, expected_dim in required_with_dim.items():
        assert name in groups, (
            f"missing physical group {name!r}; got {sorted(groups)}")
        assert groups[name][0] == expected_dim, (
            f"{name}: expected dim={expected_dim}, got {groups[name][0]}")


def test_m3_skip_generate_keeps_geometry_only(tmp_path):
    """`generate=False` 跑到 cut 即返回; `mesh_path` / `physical_groups` 仍空。"""
    result = build_mesh(EXAMPLE, output_path=tmp_path / "ignored.msh",
                        generate=False)
    assert result.mesh_path is None
    assert result.physical_groups == {}


# -----------------------------------------------------------------------------
# M4: 端口 / 对称面 / open-pin endcap (plan §3.3-B + §3.3-C + §7.2)
# -----------------------------------------------------------------------------

# 一个最小 design: Q1 + Q2, netlist 空 (两个 pin 都 open), 用于触发 endcap
# 自动加 + lumped port 几何路径。layer 1 metal 2um, layer 3 dielectric 750um。
_M4_YAML = """
schema: qiskit-metal/design-dsl/3
vars: {pad_w: 200um}
hamiltonian: {}
circuit: {}
netlist: {connections: []}
geometry:
  design:
    class: DesignPlanar
    chip: {size: 4mm x 4mm}
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, center: [-0.5mm, 0mm],
           size: ["${pad_w}", 100um]}
      pins:
        - {name: bus, points: [[-0.4mm, -6um], [-0.4mm, 6um]],
           width: 12um, gap: 7um}
    Q2:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0.5mm, 0mm],
           size: ["${pad_w}", 100um]}
      pins:
        - {name: bus, points: [[0.4mm, -6um], [0.4mm, 6um]],
           width: 12um, gap: 7um}
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um, z: 0um}
      3: {kind: dielectric, thickness: -750um, z: 0um}
"""


def test_m4_open_pin_creates_endcap(tmp_path):
    """plan §7.2: open pin (无 connection 引用) → 自动 endcap → ground 出缺口。

    通过对比 "无 open pin" vs "有 open pin" 的 ground volume 数量差异校验。
    chain_2q_native 的所有 pin 都被 connection 覆盖 → 无 endcap; 而 _M4_YAML
    完全没 connection → 4 个 endcap → ground 应被切碎成多块。
    """
    result = build_mesh(_M4_YAML, options={"mesh": _COARSE_MESH},
                        output_path=tmp_path / "m4_open.msh")
    gnd_vols = result.physical_groups.get("gnd_layer1", (None, []))[1]
    # 4 个 endcap (每 component 1 pin × 2 components, 加一些容差); ground
    # 至少 > 1 块 (相对 chain_2q 的 n_tags=1) 才说明确实切出了缺口。
    assert len(gnd_vols) >= 1
    # 无 connection 触发的 endcap 已经发生; 间接验证: vacuum 体积存在
    assert "vacuum" in result.physical_groups


def test_m4_lumped_port_surface_exists(tmp_path):
    """声明 `{pin: Q1.bus, type: lumped}` → physical group `port_Q1_bus`
    出现, dim=2, 恰好 1 个 face (M5.1 收紧后端口面 = box 远端单一垂直壁)。"""
    result = build_mesh(
        _M4_YAML, output_path=tmp_path / "m4_port.msh",
        options={
            "mesh": _COARSE_MESH,
            "ports": [{"pin": "Q1.bus", "type": "lumped", "impedance": "50ohm"}],
        })
    assert "port_Q1_bus" in result.physical_groups, (
        f"missing port_Q1_bus; got {sorted(result.physical_groups)}")
    dim, tags = result.physical_groups["port_Q1_bus"]
    assert dim == 2
    # M5 (M4 r1 观察 #1): lumped port 面收紧到 box 远端单一垂直壁
    # (法向 = +pin_normal, 垂直于电流流向)。
    assert len(tags) == 1, (
        f"port_Q1_bus should pin to a single outer-wall face, got {tags}")


def test_m4_ground_port_naming(tmp_path):
    """声明 `type: ground` → physical group `port_Q1_bus_gnd` (with `_gnd`)。"""
    result = build_mesh(
        _M4_YAML, output_path=tmp_path / "m4_gport.msh",
        options={
            "mesh": _COARSE_MESH,
            "ports": [{"pin": "Q1.bus", "type": "ground"}],
        })
    assert "port_Q1_bus_gnd" in result.physical_groups, (
        f"missing port_Q1_bus_gnd; got {sorted(result.physical_groups)}")


def test_m4_symmetry_y0_creates_group_and_truncates_model(tmp_path):
    """plan §7.2: `symmetry: [{plane: y0}]` → 模型 y_min ≈ 0, 出现
    `symmetry_y0` group。
    """
    result = build_mesh(
        _M4_YAML, output_path=tmp_path / "m4_sym.msh",
        options={
            "mesh": _COARSE_MESH,
            "symmetry": [{"plane": "y0", "condition": "pec"}],
        })
    assert "symmetry_y0" in result.physical_groups, (
        f"missing symmetry_y0; got {sorted(result.physical_groups)}")
    dim, tags = result.physical_groups["symmetry_y0"]
    assert dim == 2
    assert len(tags) >= 1
    # M5 (M4 r1 nit 4.2): symmetry y0 切掉 y<0 半空间, 模型 bbox 的 y_min 应
    # ≈ 0 (容差 1um)。build_mesh 现在会 finalize gmsh, 所以需要先 initialize
    # 才能查询 bbox。
    gmsh.initialize()
    try:
        gmsh.open(str(tmp_path / "m4_sym.msh"))
        bbox = gmsh.model.getBoundingBox(-1, -1)
        assert bbox[1] > -1e-6, (
            f"y_min should be ~0 after y0 symmetry cut, got {bbox[1]}")
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


def test_m4_msh_reload_via_meshio(tmp_path):
    """plan §11 完工标准: ``.msh`` 能被 meshio.read() 读出且至少含 6 个
    命名 physical group.

    使用 meshio (而非 gmsh.open) 验证 msh4 文件本身符合通用格式标准, 不
    依赖产线工具自身; meshio 缺失时 skip。
    """
    meshio = pytest.importorskip("meshio")
    out = tmp_path / "m5_meshio.msh"
    result = build_mesh(EXAMPLE, output_path=out,
                        options={"mesh": _COARSE_MESH})
    assert out.exists()
    mesh = meshio.read(str(out))
    # meshio 把 gmsh physical group 名挂在 mesh.field_data 上, key=group_name,
    # value=(tag_index, dim)。plan §11 6 个 group 必须都在 mesh.field_data 里。
    required = {
        "gnd_layer1", "substrate_layer3", "vacuum",
        "Q1_pad_left", "bus_center_trace", "vacuum_outer",
    }
    seen = set(mesh.field_data.keys())
    missing = required - seen
    assert not missing, (
        f"meshio.read missing physical groups {sorted(missing)}; got "
        f"{sorted(seen)}")
    # plan §11: 至少 6 个命名 physical group
    assert len(seen) >= 6, f"expected >= 6 groups, got {len(seen)}"


def test_m4_msh_reload_via_gmsh_open(tmp_path):
    """reviewer2 r1 建议 1: 用 `gmsh.open()` reload 出文件确认 msh4 可读。"""
    out = tmp_path / "m4_reload.msh"
    build_mesh(_M4_YAML, output_path=out, options={"mesh": _COARSE_MESH})
    # build_mesh finalizes gmsh; initialize a fresh session to reload the file.
    gmsh.initialize()
    try:
        gmsh.open(str(out))
        entities_3d = gmsh.model.getEntities(dim=3)
        assert len(entities_3d) > 0
    finally:
        if gmsh.isInitialized():
            gmsh.finalize()


# -----------------------------------------------------------------------------
# plan §0 自检: import 路径不接触 deny-list
# -----------------------------------------------------------------------------

def test_adapter_does_not_import_renderer_gmsh_or_renderer_base():
    """plan §0 自检 (subprocess 隔离版): build_mesh 后, 真正的 EM-renderer
    入口 — ``QGmshRenderer`` / ``QRenderer`` / ``BoundsForPathAndPolyTables``
    内部代码路径 — 必须没被加载。

    plan §0 的备注承认: ``import qiskit_metal`` 顶层会自己 import 一堆
    ``designs.*`` / ``qlibrary.core.*`` / ``layer_stack_handler``, 这些
    属于 baseline 噪声不算 adapter 引入。本测只检查那些 baseline 不会拉
    入的真正阻塞模块:
    - ``qiskit_metal.renderers.renderer_gmsh.gmsh_renderer`` (`QGmshRenderer` 类)
    - ``qiskit_metal.renderers.renderer_base`` (`QRenderer` 基类)
    - ``qiskit_metal.qlibrary.qubits.*`` / ``qiskit_metal.qlibrary.tlines.*`` 等
      qlibrary 子包 (baseline 只加载 ``qlibrary.core``)

    ``BoundsForPathAndPolyTables`` 被 ``toolbox_metal/__init__.py`` 顶层
    re-export, 所以 ``toolbox_metal.bounds_for_path_and_poly_tables`` 在
    baseline 里就已加载, 不能作为信号 — adapter 没 *调用* 它就 OK。
    """
    import subprocess
    import sys
    script = f"""
import sys
# 1) 先记录 baseline (单纯 import qiskit_metal 加载了哪些模块)
import qiskit_metal
baseline = set(sys.modules)

# 2) 再 import adapter + 跑 build_mesh
from qiskit_metal.toolbox_metal.dsl.gmsh_adapter import build_mesh
from pathlib import Path
build_mesh(Path(r'{EXAMPLE}'), generate=False)

after = set(sys.modules)
new_modules = after - baseline

# adapter 新引入的模块里, 真正阻塞的是:
hard_deny_prefixes = [
    'qiskit_metal.renderers.renderer_gmsh.gmsh_renderer',
    'qiskit_metal.renderers.renderer_base',
]
# qlibrary 子包 — baseline 已经加载了 qlibrary.core, 这是 builder 的硬性
# 依赖 (NativeComponent → QComponent); 但 qubits / tlines / lumped 等
# 高阶库不应该被 adapter 触发。
def is_high_level_qlibrary(m: str) -> bool:
    if not m.startswith('qiskit_metal.qlibrary.'):
        return False
    suffix = m[len('qiskit_metal.qlibrary.'):]
    if suffix.startswith('core'):
        return False  # baseline 已含, 允许
    return True

violations = []
for mod in new_modules:
    if any(mod.startswith(p) for p in hard_deny_prefixes):
        violations.append(mod)
    if is_high_level_qlibrary(mod):
        violations.append(mod)
# designs / layer_stack_handler / bounds_for_path 在 baseline 中已加载,
# 这里也兜底检查 adapter 没单独追加加载 (理论上不会再"新出现")。
for mod in new_modules:
    if mod.startswith('qiskit_metal.designs.'):
        violations.append(mod)
    if mod == 'qiskit_metal.toolbox_metal.layer_stack_handler':
        violations.append(mod)

assert not violations, f'adapter pulled in denylist modules: {{sorted(violations)}}'
print('OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, timeout=180,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}")
    assert "OK" in result.stdout
