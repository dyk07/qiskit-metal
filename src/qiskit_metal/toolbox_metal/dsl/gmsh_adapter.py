# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter: native YAML → ``.msh`` 端到端入口。

设计要求 (`02_plan.md §0` 硬性前提):
- 唯一接入点 = `build_ir()` → `DesignIR`; 不实例化任何 ``QDesign``。
- 不依赖 ``QGmshRenderer`` / ``LayerStackHandler`` / ``BoundsForPathAndPolyTables``。
- adapter 内部统一 SI (米); YAML / IR 中的 mm float 在入口处一次性 ×1e-3。

M2 阶段覆盖 plan §3.3 的 **阶段 A / B / D** (shapely → OCC → extrude → cut)。
fragment / physical groups / mesh export 留到 M3; ports / symmetry / endcap 留到 M4。

允许 import (`02_plan.md §0.3` allow-list):
- 本包 (`qiskit_metal.toolbox_metal.dsl.*`)
- `qiskit_metal.toolbox_metal.parsing.parse_value`
- `qiskit_metal.renderers.renderer_gmsh.gmsh_utils` 中的 pure-function
- `qiskit_metal.toolbox_python.utility_functions.clean_name` / `bad_fillet_idxs`
- third-party: `gmsh`, `shapely`, `numpy`, 标准库
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Union

from qiskit_metal.renderers.renderer_gmsh.gmsh_utils import _require_gmsh

from .builder import (
    ComponentIR,
    DesignIR,
    _parse_gmsh_simulation,
    build_ir,
)
from ._helpers import deep_merge as _deep_merge
from ._gmsh_geometry import (
    GeomTracker,
    compute_chip_bbox_si,
    compute_open_pins,
    render_component,
    render_open_pin_endcap,
    resolve_port_surfaces,
)
from ._gmsh_layers import (
    apply_cuts,
    apply_symmetry_cuts,
    fragment_everything,
    render_layer_grounds,
    render_vacuum_box,
)
from ._gmsh_mesh import define_size_fields, generate_mesh, write_mesh
from ._gmsh_physical import assign_physical_groups

try:
    import gmsh
except ImportError:  # pragma: no cover
    gmsh = None


__all__ = [
    "GmshOptions",
    "GmshMeshResult",
    "build_mesh",
    "DEFAULT_LAYER_STACK_MM",
    "DEFAULT_AIRBOX_MM",
]


# ---------------------------------------------------------------------------
# 默认值 (与 LayerStackHandler / MultiPlanar._uwave_package 数值对齐, 不 import)
# ---------------------------------------------------------------------------

# 单位: mm (IR 约定)。adapter 入口 ×1e-3 转 SI。
DEFAULT_LAYER_STACK_MM: dict[int, dict[str, Any]] = {
    1: {"kind": "metal", "thickness": 0.002, "z": 0.0, "material": "pec"},
    3: {"kind": "dielectric", "thickness": -0.75, "z": 0.0,
        "material": "silicon", "eps_r": 11.45},
}
DEFAULT_AIRBOX_MM: dict[str, float] = {
    "top": 0.89,
    "bottom": 1.65,
    "side_buffer": 0.2,
}


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GmshOptions:
    """已规整 + SI 化的运行参数。

    所有长度字段单位 = 米 (SI); ``layer_stack[i].thickness/z`` 同样。
    ``ports / symmetry / mesh / output`` 字段 M2 阶段不消费, 透传给 M3/M4。
    """

    layer_stack: dict[int, dict[str, Any]]
    airbox: dict[str, float]
    ports: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    symmetry: tuple[dict[str, str], ...] = field(default_factory=tuple)
    mesh: dict[str, Any] = field(default_factory=dict)
    output_format: str = "msh4"
    output_scaling: float = 1.0
    headless: bool = True


@dataclass(frozen=True)
class GmshMeshResult:
    """build_mesh 的返回契约。

    M2 阶段 ``mesh_path`` 为 None (还没写出 .msh), ``physical_groups`` 为
    空字典; 主要供 reviewer / smoke 校验几何 bbox 和 IR 是否被消费。
    """

    mesh_path: Optional[Path]
    physical_groups: dict[str, tuple[int, list[int]]]
    bounding_box_m: tuple[float, float, float, float]
    options: GmshOptions
    ir: DesignIR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _layer_stack_to_si(stack_mm: dict[int, dict[str, Any]]
                       ) -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for layer, spec in stack_mm.items():
        out[int(layer)] = {
            **spec,
            "thickness": float(spec["thickness"]) * 1e-3,
            "z": float(spec.get("z", 0.0)) * 1e-3,
        }
    return out


def _airbox_to_si(airbox_mm: dict[str, Any]) -> dict[str, float]:
    return {key: float(value) * 1e-3 for key, value in airbox_mm.items()}


def _ports_ir_to_raw(ports: Any) -> list[dict[str, Any]]:
    """把 IR 中已规范化的 ports (拆分了 component/pin) 还原成 raw spec 形态。

    `_parse_ports` 解析后 entry 形如 ``{component, pin, type, ...}``;
    raw spec 形如 ``{pin: "component.pin", type, ...}``。kwarg 走的是 raw
    形态; IR 段在被重新喂回 `_parse_gmsh_simulation` 前需要先反向规范化,
    否则 ``"." not in pin_ref`` 校验会误报。
    """
    out: list[dict[str, Any]] = []
    for entry in ports or ():
        if not isinstance(entry, Mapping):
            out.append(entry)
            continue
        if "component" in entry and "pin" in entry and "." not in str(entry["pin"]):
            rebuilt = {k: v for k, v in entry.items() if k != "component"}
            rebuilt["pin"] = f"{entry['component']}.{entry['pin']}"
            out.append(rebuilt)
        else:
            out.append(dict(entry))
    return out


# M5 (M3 r1 建议 3): mesh kwarg 单位防呆 — kwarg 与 IR 段同语义都是 mm float.
# 0.001 表示 1um (合理), 但若用户误把 SI 米 (5e-6 = 5 nm 当 mm 字面量传)
# 会触发 ×1e-3 → SI 5 nm → mesh.generate 内存爆炸 (踩坑日志见 walkthrough §5.2)。
# 上下界 (mm): [1e-5, 100]; 即 [10 nm, 10 cm]. 任何超出此范围的长度都视为
# 单位误用, 直接 raise — 这是契约 (walkthrough §5.2), 而非 best-effort 转换。
_MESH_LENGTH_MIN_MM = 1e-5    # 10 nm in mm
_MESH_LENGTH_MAX_MM = 100.0   # 10 cm in mm


def _check_mesh_length_mm(field: str, value: Any) -> None:
    """对 mesh kwarg 中的长度字段做 mm 单位合理性检查。"""
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"simulation.gmsh.mesh.{field}: expected numeric mm value, "
            f"got {value!r}") from exc
    if v <= 0:
        raise ValueError(
            f"simulation.gmsh.mesh.{field}: must be > 0 mm, got {v}")
    if v < _MESH_LENGTH_MIN_MM or v > _MESH_LENGTH_MAX_MM:
        raise ValueError(
            f"simulation.gmsh.mesh.{field}={v} mm is outside the sane range "
            f"[{_MESH_LENGTH_MIN_MM} mm, {_MESH_LENGTH_MAX_MM} mm]. mesh "
            f"kwarg 单位 = mm float (与 IR simulation.gmsh.mesh.* 同语义); "
            f"若想表示 SI 米数值, 请乘以 1000 (e.g. 5e-6 米 → 0.005 mm)。"
            f"参考 examples/dsl/.note/gmsh_walkthrough.md §5.2.")


def _normalize_options(ir_sim: dict[str, Any],
                       options_kwarg: Optional[dict[str, Any]],
                       components: list[ComponentIR],
                       variables: Optional[dict[str, Any]] = None) -> GmshOptions:
    """合并 ir.simulation.gmsh + adapter kwarg `options`, 转 SI, 兜默认。

    plan §0 + M2 review §2.1: ``options_kwarg`` 不可绕开 M1 schema 校验。这里
    把 IR 段反向规范化回 raw spec → deep-merge kwarg → 若 merged block
    非空就整段喂回 ``_parse_gmsh_simulation``, 与 ``build_ir`` 走同一套硬约
    束 (`layer_stack` 必填 / 必含 metal / 覆盖 primitive.layer /
    `thickness != 0` / port pin 引用合法 / 字段类型 等)。
    """
    ir_gmsh = ir_sim.get("gmsh", {}) or {}
    gmsh_block: dict[str, Any] = {k: v for k, v in ir_gmsh.items() if k != "ports"}
    if "ports" in ir_gmsh:
        gmsh_block["ports"] = _ports_ir_to_raw(ir_gmsh["ports"])
    # Bug 1 fix: use deep_merge so nested dicts (e.g. layer_stack) are merged
    # at the nested level rather than having the top-level key overwritten.
    if options_kwarg:
        gmsh_block = _deep_merge(gmsh_block, options_kwarg)

    # 一旦 merged block 非空, 整段重过 schema (IR 段和 kwarg 段一视同仁)。
    # 空 dict (无 YAML simulation 段、也无 kwarg) 跳过校验, 走 adapter 默认。
    # Bug 2 fix: pass real variables so ${...} expressions in options resolve.
    if gmsh_block:
        gmsh_block = _parse_gmsh_simulation(gmsh_block, variables or {}, components)

    layer_stack_mm = gmsh_block.get("layer_stack") or DEFAULT_LAYER_STACK_MM
    airbox_mm = {**DEFAULT_AIRBOX_MM, **(gmsh_block.get("airbox") or {})}

    layer_stack_si = _layer_stack_to_si(layer_stack_mm)
    airbox_si = _airbox_to_si(airbox_mm)

    output = gmsh_block.get("output", {}) or {}
    mesh_block = gmsh_block.get("mesh", {}) or {}
    # mesh 子字段 (长度) 也转 SI; conductor_refine 嵌套一层
    mesh_si: dict[str, Any] = {}
    for key in ("max_size", "min_size", "max_size_jj"):
        if key in mesh_block:
            _check_mesh_length_mm(key, mesh_block[key])
            mesh_si[key] = float(mesh_block[key]) * 1e-3
    if "conductor_refine" in mesh_block:
        refine = mesh_block["conductor_refine"] or {}
        for key, value in refine.items():
            _check_mesh_length_mm(f"conductor_refine.{key}", value)
        mesh_si["conductor_refine"] = {
            key: float(value) * 1e-3 for key, value in refine.items()
        }

    return GmshOptions(
        layer_stack=layer_stack_si,
        airbox=airbox_si,
        ports=tuple(gmsh_block.get("ports") or ()),
        symmetry=tuple(gmsh_block.get("symmetry") or ()),
        mesh=mesh_si,
        output_format=str(output.get("format", "msh4")),
        output_scaling=float(output.get("scaling", 1.0)),
    )


def _resolve_ir(source: Union[str, Path, DesignIR]) -> DesignIR:
    """plan §0 三分支: YAML 路径 / YAML 字符串 / 已构造 DesignIR。"""
    if isinstance(source, DesignIR):
        return source
    if isinstance(source, (str, Path)):
        return build_ir(source)
    raise TypeError(
        f"build_mesh requires str | Path | DesignIR; got "
        f"{type(source).__name__}. QDesign is not supported (plan §0).")


def _default_metal_layer(layer_stack_si: dict[int, dict]) -> int:
    """挑第一个 kind=metal 的 layer 作为 endcap 缺省宿主 layer。

    在 schema 校验阶段已经保证至少存在一个 metal layer (M1-fix-1)。
    """
    for layer, spec in sorted(layer_stack_si.items()):
        if spec.get("kind") == "metal":
            return layer
    raise ValueError("layer_stack contains no metal layer (schema bug)")


def _ir_ports_index(ir_ports: tuple) -> dict[tuple[str, str], dict[str, Any]]:
    """`{(component, pin): port_spec}`, 来自 ``resolved_options.ports``。"""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in ir_ports or ():
        key = (entry.get("component"), entry.get("pin"))
        if all(k is not None for k in key):
            out[key] = dict(entry)
    return out


def _stage_endcaps_and_ports(ir: DesignIR,
                             layer_stack_si: dict[int, dict],
                             ir_ports: tuple,
                             tracker: GeomTracker) -> None:
    """Stage B': 对每个 open pin 画 endcap; 对每个 port pin 同时记 port 候选。

    open pin = 未被 `derived.netlist.connections` 引用; port pin = 出现在
    `simulation.gmsh.ports` 中 (无论是否在 connections 里 — 用户显式声明
    端口的意图压倒 open/connected 推断)。
    """
    port_index = _ir_ports_index(ir_ports)
    open_pin_keys = set(compute_open_pins(ir))
    # 端口 pin 强制加 endcap (无论是否 open) — 即便它在 connection 里, 也
    # 需要打开一个对外接口
    pin_to_render = open_pin_keys | set(port_index.keys())
    if not pin_to_render:
        return
    metal_layer = _default_metal_layer(layer_stack_si)
    metal_spec = layer_stack_si[metal_layer]
    z_si = float(metal_spec["z"])
    thickness_si = float(metal_spec["thickness"])

    by_name = {comp.name: comp for comp in ir.components}
    for comp_name, pin_name in sorted(pin_to_render):
        comp = by_name.get(comp_name)
        if comp is None:
            continue
        pin_obj = next((p for p in comp.pins if p.name == pin_name), None)
        if pin_obj is None:
            continue
        port_spec = port_index.get((comp_name, pin_name))
        port_name = None
        is_lumped = True
        if port_spec is not None:
            ptype = port_spec.get("type", "lumped")
            is_lumped = (ptype == "lumped")
            # port_name 仅用于 tracker 内部 key; physical group 名走
            # PHYSICAL_GROUP_NAMING + tracker.port_metadata
            port_name = f"{comp_name}__{pin_name}"
            tracker.port_metadata[port_name] = {
                "component": comp_name,
                "pin": pin_name,
                "is_lumped": is_lumped,
            }
        render_open_pin_endcap(pin_obj, metal_layer, z_si, thickness_si,
                               tracker, port_name=port_name,
                               is_lumped=is_lumped)


def _gmsh_initialize(headless: bool, model_name: str) -> None:
    _require_gmsh()
    if gmsh.isInitialized():
        gmsh.clear()
    else:
        gmsh.initialize()
    if headless:
        gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add(model_name)


def _gmsh_finalize_optional(show_gui: bool) -> None:
    if show_gui and gmsh is not None and gmsh.isInitialized():
        gmsh.fltk.run()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_mesh(source: Union[str, Path, DesignIR],
               *,
               output_path: Optional[Union[str, Path]] = None,
               options: Optional[dict[str, Any]] = None,
               show_gui: bool = False,
               generate: bool = True) -> GmshMeshResult:
    """从 DSL YAML / `DesignIR` 构造 Gmsh mesh 并写 ``.msh``。

    Args:
        source: YAML 文件路径 / YAML 字符串 / 已构造的 ``DesignIR``。
            不接受 ``QDesign`` 或其它对象 (plan §0)。
        output_path: ``.msh`` 输出路径。``None`` 时不写文件 (`mesh_path` 仍
            为 None), 但 mesh 在内存里已经生成 — 适用于 GUI 调试。
        options: 覆盖 ``ir.simulation.gmsh``; 单位仍是 mm float, adapter
            内部转 SI。例:
            ``build_mesh(yaml, options={"layer_stack": {1: {"kind":"metal",
            "thickness":0.005}}})`` 把 metal 改 5um。
        show_gui: True 时调 ``gmsh.fltk.run()`` 打开 GUI 看几何; CI 默认 False。
        generate: True 时跑完整流水线 (fragment → physical groups → mesh);
            False 时只跑到 cut, 供 M2 风格的几何调试 (老测试入口)。

    Returns:
        ``GmshMeshResult``: ``mesh_path`` 在 ``output_path`` 给定且
        ``generate=True`` 时指向输出文件; ``physical_groups`` 在
        ``generate=True`` 时非空。
    """
    _require_gmsh()
    ir = _resolve_ir(source)
    # Bug 2 fix: forward ir.vars so ${...} expressions in options can resolve.
    resolved_options = _normalize_options(
        ir.simulation or {}, options, ir.components, variables=ir.vars or {}
    )

    # Bug 3 fix: track whether WE call gmsh.initialize() so we know whether
    # to call gmsh.finalize() in the finally block.  If gmsh was already
    # initialized before our call we only do gmsh.clear(), and we must NOT
    # finalize (the caller owns that gmsh session).
    _did_initialize = not gmsh.isInitialized()
    _gmsh_initialize(resolved_options.headless, model_name="dsl_design")

    try:
        tracker = GeomTracker()

        # Stage A + B: primitives → PlaneSurface → extrude
        for component in ir.components:
            render_component(component, resolved_options.layer_stack, tracker)
        gmsh.model.occ.synchronize()

        # Stage B': open-pin endcap + lumped/ground port box (在 ground 画
        # 出来之前不能 cut; 但 box 可以先画出来等 stage D 一起 cut)
        _stage_endcaps_and_ports(
            ir, resolved_options.layer_stack, resolved_options.ports, tracker)

        # Stage C: ground plane + vacuum box
        side_buffer_si = float(resolved_options.airbox.get(
            "side_buffer", DEFAULT_AIRBOX_MM["side_buffer"] * 1e-3))
        bbox_si = compute_chip_bbox_si(ir.components, side_buffer_si)
        render_layer_grounds(bbox_si, resolved_options.layer_stack, tracker)
        render_vacuum_box(bbox_si, resolved_options.airbox, tracker)
        gmsh.model.occ.synchronize()

        # Stage C': symmetry — cut 半空间 (必须在 stage D / E 之前)
        if resolved_options.symmetry:
            apply_symmetry_cuts(resolved_options.symmetry, tracker,
                                bbox_si, resolved_options.airbox)

        # Stage D: cut subtract primitives + endcap boxes from ground
        apply_cuts(tracker)

        mesh_path: Optional[Path] = None
        physical_groups: dict[str, tuple[int, list[int]]] = {}

        if generate:
            # Stage D': 端口面解析 (cut 之后, fragment 之前) — fragment 也会
            # 把 ports 当作 input 让 remap 正常走 (M4 r1 观察 #2, M5 修)。
            # 必须在 fragment 之前 resolve, 因为后者会重置 face tag。
            if tracker.port_box_specs:
                resolve_port_surfaces(tracker)
            # Stage E: fragment (共面缝合, dimtag 重映射)
            fragment_everything(tracker)
            # Stage F: physical groups
            physical_groups = assign_physical_groups(
                tracker, resolved_options.layer_stack,
                symmetry_specs=resolved_options.symmetry)
            # Stage G: mesh size fields + generate(3) + (可选) 写文件
            define_size_fields(tracker, resolved_options.layer_stack,
                               resolved_options.mesh)
            generate_mesh(dim=3)
            if output_path is not None:
                mesh_path = write_mesh(
                    Path(output_path),
                    output_format=resolved_options.output_format,
                    output_scaling=resolved_options.output_scaling,
                )

        result = GmshMeshResult(
            mesh_path=mesh_path,
            physical_groups=physical_groups,
            bounding_box_m=bbox_si,
            options=resolved_options,
            ir=ir,
        )

        # Show GUI before finalizing (only runs if show_gui=True).
        _gmsh_finalize_optional(show_gui)
        return result

    finally:
        # Bug 3 fix: finalize only if WE initialized (not just cleared).
        # This prevents orphaned gmsh state on exceptions and avoids leaking
        # stale mesh options across repeated build_mesh() calls in notebooks.
        if _did_initialize and gmsh is not None and gmsh.isInitialized():
            gmsh.finalize()
