# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter: 几何阶段 A / B 私有实现。

只接受 `PrimitiveIR` / `PinIR` (纯 dataclass) + 已换算 SI 的尺寸, 不引用
`QDesign` / `QGmshRenderer` / `LayerStackHandler`。允许 import:
- `qiskit_metal.renderers.renderer_gmsh.gmsh_utils` 中的 pure-function
  (`render_path_curves`, `line_width_offset_pts`, `Vec3DArray`, `Vec3D`,
  `_require_gmsh`) — 这些函数不触碰 `design.ls`。
- `qiskit_metal.toolbox_python.utility_functions.bad_fillet_idxs` (pure)
- `gmsh`, `numpy`, `shapely`, 标准库

deny-list (硬性): `qiskit_metal.designs.*`, `qiskit_metal.qlibrary.*`,
`qiskit_metal.toolbox_metal.layer_stack_handler`, `BoundsForPathAndPolyTables`,
整个 `QGmshRenderer` 类, `renderer_base`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from qiskit_metal.renderers.renderer_gmsh.gmsh_utils import (
    Vec3DArray,
    _require_gmsh,
    line_width_offset_pts,
    render_path_curves,
)
from qiskit_metal.toolbox_python.utility_functions import bad_fillet_idxs

from .builder import ComponentIR, PrimitiveIR, PinIR

try:
    import gmsh
except ImportError:  # pragma: no cover — exercised on lite installs
    gmsh = None


# ---------------------------------------------------------------------------
# 内部 tracker (替代 QGmshRenderer.paths_dict / polys_dict / juncs_dict / ...)
# ---------------------------------------------------------------------------

@dataclass
class GeomTracker:
    """记录所有 adapter 创建的 OCC 实体的 dimtag 表。

    所有 key 用 (component_name, primitive_name) 二元组以避免命名冲突;
    fragment 后通过 ``remap_tags`` 更新。
    """

    # layer → {(component, primitive): [volume_tags]}
    polys: dict[int, dict[tuple[str, str], list[int]]] = field(default_factory=dict)
    paths: dict[int, dict[tuple[str, str], list[int]]] = field(default_factory=dict)
    # junction 是 2D surface, 不 extrude
    juncs: dict[int, dict[tuple[str, str], list[int]]] = field(default_factory=dict)
    # layer → [volume_tags] (待 cut, primitive.subtract=True)
    subtracts: dict[int, list[int]] = field(default_factory=dict)
    # layer → [box_tags] (open-pin endcap, 由 M4 填充)
    endcap_subtracts: dict[int, list[int]] = field(default_factory=dict)
    # 每个 layer 的 ground plane volume tags (cut 之后会被 remap)
    layer_ground: dict[int, list[int]] = field(default_factory=dict)
    vacuum_box: Optional[int] = None
    # port_name → [surface_tags] (M4 填充, fragment 之后是真实 face tag)
    ports: dict[str, list[int]] = field(default_factory=dict)
    # port_name → [_PortBoxSpec] (M4 中间态: cut 之前的 endcap box +
    # 朝向真空的 normal; cut 之后 `resolve_port_surfaces` 从 ground
    # 缺口边界筛出 port face, 替换为真正的 surface tag list)
    port_box_specs: dict[str, list["_PortBoxSpec"]] = field(default_factory=dict)
    # port_name → {component, pin, is_lumped} (M4 填充, 给 physical group
    # 阶段命名用; M5 提升为正式字段, 取代旧版 `tracker._port_metadata`)
    port_metadata: dict[str, dict[str, Any]] = field(default_factory=dict)
    # symmetry plane name → [surface_tags] (M4 填充)
    symmetry_surfaces: dict[str, list[int]] = field(default_factory=dict)

    def _ensure_layer(self,
                      table: dict[int, dict[tuple[str, str], list[int]]],
                      layer: int) -> dict[tuple[str, str], list[int]]:
        return table.setdefault(layer, {})

    def add_poly(self, component: str, primitive: str, layer: int,
                 tag: int) -> None:
        self._ensure_layer(self.polys, layer).setdefault(
            (component, primitive), []).append(tag)

    def add_path(self, component: str, primitive: str, layer: int,
                 tag: int) -> None:
        self._ensure_layer(self.paths, layer).setdefault(
            (component, primitive), []).append(tag)

    def add_junction(self, component: str, primitive: str, layer: int,
                     tag: int) -> None:
        self._ensure_layer(self.juncs, layer).setdefault(
            (component, primitive), []).append(tag)

    def add_subtract(self, layer: int, tag: int) -> None:
        self.subtracts.setdefault(layer, []).append(tag)

    # ---------------------------------------------------------------------
    # fragment 后的 dimtag 重映射 (替代 QGmshRenderer:899-912 的内联 zip 循环)
    # ---------------------------------------------------------------------

    def remap(self, old_to_new: dict[tuple[int, int], list[tuple[int, int]]]
              ) -> None:
        """把所有内部 tag 表按 ``old_to_new`` 映射更新。

        ``old_to_new`` 来自 ``gmsh.model.occ.fragment``: 把每个 *输入*
        dimtag 映射到 *fragment 之后* 的一组 dimtag (通常 1 个; 偶尔被
        切碎成多个)。本方法对 `polys / paths / juncs / layer_ground /
        vacuum_box / ports / symmetry_surfaces` 全表 in-place 改写。

        约定: 同维度的 tag 才会被替换 (e.g. 一个 3D volume 不会被 mapping
        到 2D surface)。
        """
        def _expand(dim: int, tag: int) -> list[int]:
            # 区分三种语义:
            # - key 不在 old_to_new: 该 tag 没参与 fragment, 保留 (返回 [tag])
            # - key 存在 + mapping 含同维 tag: 替换为这些 tag
            # - key 存在 + mapping 不含同维 tag (体被完全消耗 / 维度变化):
            #   返回 [], tracker 表里自然丢掉 stale tag (reviewer2 r1 建议 2)
            mapped = old_to_new.get((dim, tag))
            if mapped is None:
                return [tag]
            return [t for (d, t) in mapped if d == dim]

        def _remap_list(dim: int, tags: list[int]) -> list[int]:
            out: list[int] = []
            for tag in tags:
                out.extend(_expand(dim, tag))
            return out

        for layer in list(self.polys.keys()):
            for key in list(self.polys[layer].keys()):
                self.polys[layer][key] = _remap_list(3, self.polys[layer][key])
        for layer in list(self.paths.keys()):
            for key in list(self.paths[layer].keys()):
                self.paths[layer][key] = _remap_list(3, self.paths[layer][key])
        for layer in list(self.juncs.keys()):
            for key in list(self.juncs[layer].keys()):
                self.juncs[layer][key] = _remap_list(2, self.juncs[layer][key])
        for layer in list(self.layer_ground.keys()):
            self.layer_ground[layer] = _remap_list(3, self.layer_ground[layer])
        if self.vacuum_box is not None:
            mapped = _expand(3, self.vacuum_box)
            self.vacuum_box = mapped[0] if mapped else self.vacuum_box
        for name in list(self.ports.keys()):
            self.ports[name] = _remap_list(2, self.ports[name])
        for name in list(self.symmetry_surfaces.keys()):
            self.symmetry_surfaces[name] = _remap_list(
                2, self.symmetry_surfaces[name])


# ---------------------------------------------------------------------------
# Stage A: shapely → OCC PlaneSurface
# ---------------------------------------------------------------------------

def _add_polygon_surface(coords_si: np.ndarray, z_si: float) -> int:
    """从外环坐标构造 PlaneSurface, 返回 surface tag。

    `coords_si` 是 (N, 2) numpy float, 单位 SI 米; shapely 把首尾点闭合,
    这里去重。
    """
    if len(coords_si) >= 2 and np.allclose(coords_si[0], coords_si[-1]):
        coords_si = coords_si[:-1]
    point_tags = [
        gmsh.model.occ.addPoint(float(x), float(y), z_si)
        for x, y in coords_si
    ]
    line_tags = []
    n = len(point_tags)
    for i, p in enumerate(point_tags):
        q = point_tags[(i + 1) % n]
        line_tags.append(gmsh.model.occ.addLine(p, q))
    loop = gmsh.model.occ.addCurveLoop(line_tags)
    return gmsh.model.occ.addPlaneSurface([loop])


def render_polygon_primitive(primitive: PrimitiveIR, z_si: float,
                             thickness_si: float, tracker: GeomTracker,
                             *, component: str) -> None:
    """画一个 ``kind=poly`` primitive 并 extrude 成 3D volume。

    `primitive.geometry` 是 shapely Polygon, 坐标已经是 mm float; 这里转 SI。
    内孔: 用 OCC `cut(outer_surface, inner_surface)` 减出来。
    """
    _require_gmsh()
    polygon = primitive.geometry
    outer_si = np.array(polygon.exterior.coords, dtype=float) * 1e-3
    surface = _add_polygon_surface(outer_si, z_si)
    for interior in polygon.interiors:
        inner_si = np.array(interior.coords, dtype=float) * 1e-3
        inner_surface = _add_polygon_surface(inner_si, z_si)
        cut_result, _ = gmsh.model.occ.cut([(2, surface)],
                                           [(2, inner_surface)])
        if not cut_result:
            raise RuntimeError(
                f"OCC cut produced empty surface for {component}.{primitive.name}")
        surface = cut_result[0][1]

    extruded = gmsh.model.occ.extrude(
        [(2, surface)], dx=0.0, dy=0.0, dz=thickness_si)
    volume_tags = [tag for dim, tag in extruded if dim == 3]
    if not volume_tags:
        raise RuntimeError(
            f"OCC extrude produced no volume for {component}.{primitive.name}")
    volume = volume_tags[0]

    if primitive.subtract:
        tracker.add_subtract(primitive.layer, volume)
    else:
        tracker.add_poly(component, primitive.name, primitive.layer, volume)


def render_path_primitive(primitive: PrimitiveIR, z_si: float,
                          thickness_si: float, tracker: GeomTracker,
                          *, component: str) -> None:
    """画 ``kind=path`` primitive: shapely LineString + width + fillet → 圆角导体。"""
    _require_gmsh()
    line = primitive.geometry
    width_mm = primitive.width
    fillet_mm = primitive.fillet
    if width_mm is None or width_mm <= 0:
        raise ValueError(
            f"{component}.{primitive.name}: path width must be > 0 mm")
    width_si = float(width_mm) * 1e-3
    fillet_si = float(fillet_mm) * 1e-3 if fillet_mm else 0.0

    coords_mm = list(line.coords)
    coords_si = [
        np.array([float(x) * 1e-3, float(y) * 1e-3, z_si]) for x, y in coords_mm
    ]
    vecs = Vec3DArray(points=coords_si)
    # bad_fillet_idxs 期望 list[tuple]; 用 SI 坐标比较距离与 fillet_si 同尺度。
    coords_si_xy = [(p[0], p[1]) for p in coords_si]
    bad = bad_fillet_idxs(coords_si_xy, fillet_si)
    curves = render_path_curves(vecs, z_si, fillet_si, width_si, bad)

    loop = gmsh.model.occ.addCurveLoop(curves)
    surface = gmsh.model.occ.addPlaneSurface([loop])

    extruded = gmsh.model.occ.extrude(
        [(2, surface)], dx=0.0, dy=0.0, dz=thickness_si)
    volume_tags = [tag for dim, tag in extruded if dim == 3]
    if not volume_tags:
        raise RuntimeError(
            f"OCC extrude produced no volume for {component}.{primitive.name}")
    volume = volume_tags[0]

    if primitive.subtract:
        tracker.add_subtract(primitive.layer, volume)
    else:
        tracker.add_path(component, primitive.name, primitive.layer, volume)


def render_junction_primitive(primitive: PrimitiveIR, z_si: float,
                              thickness_si: float, tracker: GeomTracker,
                              *, component: str) -> None:
    """画 JJ 矩形, 留 2D surface 在 layer 中心 z (照 `QGmshRenderer:467` 语义)。"""
    _require_gmsh()
    line = primitive.geometry
    width_mm = primitive.width
    if width_mm is None or width_mm <= 0:
        raise ValueError(
            f"{component}.{primitive.name}: junction width must be > 0 mm")
    width_si = float(width_mm) * 1e-3

    coords_mm = list(line.coords)
    coords_si = [
        np.array([float(x) * 1e-3, float(y) * 1e-3, z_si]) for x, y in coords_mm
    ]
    vecs = Vec3DArray(points=coords_si)
    if len(vecs.path_vecs) == 0:
        raise ValueError(
            f"{component}.{primitive.name}: junction needs at least 2 points")
    v1, v2 = line_width_offset_pts(
        vecs.points[0], vecs.path_vecs[0], width_si, z_si, ret_pts=False)
    v3, v4 = line_width_offset_pts(
        vecs.points[1], vecs.path_vecs[0], width_si, z_si, ret_pts=False)
    # 与 QGmshRenderer 一样根据 v1-v3 / v1-v4 距离选 winding
    d13 = float(np.linalg.norm(v1 - v3))
    d14 = float(np.linalg.norm(v1 - v4))
    ordered = [v1, v2, v4, v3] if d13 <= d14 else [v1, v2, v3, v4]
    pts = [gmsh.model.occ.addPoint(v[0], v[1], z_si) for v in ordered]
    lines = []
    for i, p in enumerate(pts):
        q = pts[(i + 1) % len(pts)]
        lines.append(gmsh.model.occ.addLine(p, q))
    loop = gmsh.model.occ.addCurveLoop(lines)
    surface = gmsh.model.occ.addPlaneSurface([loop])
    # JJ 放在 layer 中心: 沿 z 平移 thickness/2 (与 QGmshRenderer:508 一致)
    gmsh.model.occ.translate([(2, surface)], dx=0.0, dy=0.0,
                             dz=thickness_si / 2)
    tracker.add_junction(component, primitive.name, primitive.layer, surface)


def render_component(component_ir: ComponentIR,
                     layer_stack_si: dict[int, dict],
                     tracker: GeomTracker) -> None:
    """遍历一个 component 的所有 primitives, 按 layer 厚度/中心绘制。"""
    for primitive in component_ir.primitives:
        if primitive.helper:
            continue
        layer = primitive.layer
        if layer not in layer_stack_si:
            raise KeyError(
                f"layer {layer} (primitive {component_ir.name}."
                f"{primitive.name}) missing from layer_stack")
        layer_spec = layer_stack_si[layer]
        z_si = float(layer_spec["z"])
        thickness_si = float(layer_spec["thickness"])
        if primitive.kind == "poly":
            render_polygon_primitive(primitive, z_si, thickness_si,
                                     tracker, component=component_ir.name)
        elif primitive.kind == "path":
            render_path_primitive(primitive, z_si, thickness_si,
                                  tracker, component=component_ir.name)
        elif primitive.kind == "junction":
            render_junction_primitive(primitive, z_si, thickness_si,
                                      tracker, component=component_ir.name)
        else:
            raise ValueError(
                f"Unsupported primitive kind: {primitive.kind!r} "
                f"({component_ir.name}.{primitive.name})")


# ---------------------------------------------------------------------------
# Stage B': open-pin endcap + lumped/ground port 面 (M4)
# ---------------------------------------------------------------------------

def _pin_midpoint_normal_mm(pin: PinIR) -> tuple[np.ndarray, np.ndarray]:
    """从 PinIR.points (2 个端点) 算 (midpoint_xy_mm, unit_normal_xy)。

    `points` 是 [[x1,y1], [x2,y2]] (mm); pin 朝向是 segment 的 *右手法线*
    指向 chip 外侧 (与 `add_endcaps:669` 的 `normal` 字段语义对齐)。
    """
    p1 = np.asarray(pin.points[0], dtype=float)
    p2 = np.asarray(pin.points[1], dtype=float)
    mid = (p1 + p2) * 0.5
    seg = p2 - p1
    # 右手法线: (dy, -dx) 单位化
    n = np.array([seg[1], -seg[0]], dtype=float)
    norm = float(np.linalg.norm(n))
    if norm == 0.0:
        raise ValueError(
            f"pin {pin.component}.{pin.name}: points are identical, cannot "
            f"derive normal")
    n /= norm
    return mid, n


def compute_open_pins(ir: "DesignIR") -> list[tuple[str, str]]:
    """`derived.netlist.connections` 引用过的 (component, pin) 视作 connected;
    其余视作 open pins。返回 (component, pin) 元组列表 (保序)。

    与 `QGmshRenderer.add_endcaps(open_pins=...)` 的默认语义对齐 — endcap
    应该只对 *没有相邻 component 来对接* 的 pin 加, 否则 cut 掉的 ground
    会跟相邻 trace 冲突。
    """
    connected: set[tuple[str, str]] = set()
    derived = ir.derived or {}
    netlist = derived.get("netlist", {})
    for conn in netlist.get("connections", ()) or ():
        for endpoint_key in ("from", "to"):
            ep = conn.get(endpoint_key) or {}
            comp = ep.get("component")
            pin = ep.get("pin")
            if comp is not None and pin is not None:
                connected.add((comp, pin))

    open_pins: list[tuple[str, str]] = []
    for component in ir.components:
        for pin in component.pins:
            key = (component.name, pin.name)
            if key not in connected:
                open_pins.append(key)
    return open_pins


def render_open_pin_endcap(pin: PinIR, layer: int, z_si: float,
                           thickness_si: float, tracker: GeomTracker,
                           *, port_name: Optional[str] = None,
                           is_lumped: bool = False) -> None:
    """画一个 endcap box: 把它 cut 掉 ground 形成缺口; 如果 port_name 给出,
    顺手把面向真空的那一面收进 ``tracker.ports[port_name]``。

    几何与 ``add_endcaps:674-700`` 一致:
        - rect_mid = mid + normal * gap/2
        - 若 normal 主轴是 x: dx=gap, dy=width+2*gap; 反之 swap
        - extrude 到 layer thickness 形成 3D box

    单位约定: ``pin.points / width / gap`` 都是 mm; 函数入参 z_si /
    thickness_si 是 SI 米; 内部按 SI 算 OCC 坐标。``layer`` 是 pin
    所属 ground layer (调用方按 plan §3.3-B 自己决定; 一般 = component
    的 metal layer)。
    """
    _require_gmsh()
    if pin.gap is None or pin.gap <= 0:
        raise ValueError(
            f"pin {pin.component}.{pin.name}: endcap requires positive gap "
            f"(got {pin.gap!r}); declare `gap:` in pin spec.")
    mid_mm, normal = _pin_midpoint_normal_mm(pin)
    width_si = float(pin.width) * 1e-3
    gap_si = float(pin.gap) * 1e-3
    rect_mid_mm = mid_mm + normal * (pin.gap * 0.5)
    rect_mid_si = rect_mid_mm * 1e-3

    if abs(normal[0]) > abs(normal[1]):
        dx, dy = gap_si, width_si + 2 * gap_si
    else:
        dx, dy = width_si + 2 * gap_si, gap_si
    x0 = float(rect_mid_si[0]) - dx * 0.5
    y0 = float(rect_mid_si[1]) - dy * 0.5
    box = gmsh.model.occ.addBox(x0, y0, z_si, dx, dy, thickness_si)
    tracker.endcap_subtracts.setdefault(layer, []).append(box)

    if port_name is not None:
        # endcap box 在 cut 之后留下 ground 矩形孔; 4 个垂直壁 + (可能) 底
        # 面 + 顶面共面到大 ground 面而无独立 face. M5 收紧 (M4 r1 观察 #1):
        # 端口面 = box 远离 trace 的那一侧垂直壁 (单一面, 法向 = +pin_normal)
        # — 这正是 EM lumped port 的标准位置 (与电流流向垂直)。
        top_z_si = z_si + thickness_si if thickness_si > 0 else z_si
        tracker.port_box_specs.setdefault(port_name, []).append(
            _PortBoxSpec(box_center_si=(float(rect_mid_si[0]),
                                        float(rect_mid_si[1]),
                                        z_si + thickness_si * 0.5),
                         half_size_si=(dx * 0.5, dy * 0.5,
                                       abs(thickness_si) * 0.5),
                         top_z_si=float(top_z_si),
                         pin_normal_xy=(float(normal[0]), float(normal[1])),
                         layer=layer,
                         is_lumped=is_lumped))


@dataclass
class _PortBoxSpec:
    """记录 endcap box 的体中心 + 半边长 + pin 法向 (SI), 用于 cut + fragment
    之后在 ground 边界面里筛出 *单一* 端口面 (M4 r1 观察 #1 收紧)。

    端口面语义 (M5 实现): box 在 ground 上 cut 出矩形孔后, ground 内壁出现
    4 个 ±box-normal 的垂直面 + 1 个底面 (z=z_si, 层与孔同高时与原 ground
    底面共面)。EM lumped port 应取垂直于 pin 法向的 *单一* 面 — 即 box
    远离 trace 的那一侧 (中心 xy 距 box 中心 = +pin_normal*gap/2 那一面)。

    ``top_z_si`` 留给未来扩展 (e.g. box 顶部独立面的设计), 当前不参与筛选;
    ``pin_normal_xy`` 是 pin 几何的右手法线 (单位向量) 指向 chip 外侧, 与
    `add_endcaps:669` 的 ``normal`` 字段语义对齐。
    """
    box_center_si: tuple[float, float, float]
    half_size_si: tuple[float, float, float]
    top_z_si: float
    pin_normal_xy: tuple[float, float]
    layer: int
    is_lumped: bool


def _face_is_outer_wall(face_center: tuple[float, float, float],
                        box_center: tuple[float, float, float],
                        half_size: tuple[float, float, float],
                        pin_normal_xy: tuple[float, float],
                        *, tol: float | None = None) -> bool:
    """筛 endcap box 的 *远端垂直面* (中心位于 box_center + pin_normal*gap/2)。

    box 4 个垂直面中心分别位于 box_center ± half_size 各方向; pin_normal
    的主轴 (绝对值大的那个分量) 决定 box 的 gap 维度 → 远端面 = box 中心
    沿 +pin_normal 偏移 half_size_axis 那一点。
    """
    if tol is None:
        max_dim = max(half_size) if max(half_size) > 0 else 1.0
        tol = max(max_dim * 1e-3, 1e-9)
    axis = 0 if abs(pin_normal_xy[0]) > abs(pin_normal_xy[1]) else 1
    sign = 1.0 if pin_normal_xy[axis] >= 0 else -1.0
    expected = box_center[axis] + sign * half_size[axis]
    if abs(face_center[axis] - expected) > tol:
        return False
    # 同侧轴 (axis 的正交方向) 的 face center 必须在 box 范围内
    other = 1 - axis
    if abs(face_center[other] - box_center[other]) > half_size[other] + tol:
        return False
    # z 方向: face center 在 box z 范围内 (垂直壁的中心位于 box 中段)
    if abs(face_center[2] - box_center[2]) > half_size[2] + tol:
        return False
    return True


def _face_is_bottom_wall(face_center: tuple[float, float, float],
                         box_center: tuple[float, float, float],
                         half_size: tuple[float, float, float],
                         *, tol: float | None = None) -> bool:
    """Select the bottom z-face of an endcap box for ground-port assignment."""
    if tol is None:
        max_dim = max(half_size) if max(half_size) > 0 else 1.0
        tol = max(max_dim * 1e-3, 1e-9)
    expected_z = box_center[2] - half_size[2]
    if abs(face_center[2] - expected_z) > tol:
        return False
    if abs(face_center[0] - box_center[0]) > half_size[0] + tol:
        return False
    if abs(face_center[1] - box_center[1]) > half_size[1] + tol:
        return False
    return True


def resolve_port_surfaces(tracker: GeomTracker) -> None:
    """cut + sync 之后, 把 ``tracker.port_box_specs`` 转成
    ``tracker.ports`` (port_name → [face_tag, ...])。

    每个 port box 在 cut 之后已消失, 它的 *朝真空* 那一面 (法向 = ±z,
    具体方向看 layer.thickness 正负) 留在 ground 缺口处。在该 layer
    的 ground volume 边界 (`getBoundary`) 里筛: face 中心在 endcap
    bbox 内且 z 接近 box 顶部 (thickness > 0) 或底部 (thickness < 0)
    的面即是。
    """
    _require_gmsh()
    if not tracker.port_box_specs:
        return
    # 按 layer 缓存 ground 边界 face 信息, 避免重复查
    layer_faces: dict[int, list[tuple[int, tuple[float, float, float]]]] = {}
    for layer, ground_tags in tracker.layer_ground.items():
        if not ground_tags:
            layer_faces[layer] = []
            continue
        boundary = gmsh.model.getBoundary(
            [(3, t) for t in ground_tags],
            combined=False, oriented=False, recursive=False)
        entries: list[tuple[int, tuple[float, float, float]]] = []
        for dim, tag in boundary:
            if dim != 2:
                continue
            face_tag = abs(int(tag))
            fc = gmsh.model.occ.getCenterOfMass(2, face_tag)
            entries.append((face_tag, (fc[0], fc[1], fc[2])))
        layer_faces[layer] = entries

    for port_name, specs in tracker.port_box_specs.items():
        resolved: list[int] = []
        for spec in specs:
            candidates = layer_faces.get(spec.layer, [])
            for face_tag, fc in candidates:
                # Both lumped and ground ports use the outer vertical wall of
                # the endcap box hole as the reference face.  Ground ports are
                # distinguished by name suffix ("_gnd") applied in
                # assign_physical_groups; a dedicated z-face selection for
                # ground contacts is deferred until the geometry layer can
                # guarantee a closed bottom face (M5).
                if _face_is_outer_wall(fc, spec.box_center_si,
                                       spec.half_size_si, spec.pin_normal_xy):
                    resolved.append(face_tag)
        # 去重保序
        dedup: list[int] = []
        seen: set[int] = set()
        for t in resolved:
            if t not in seen:
                seen.add(t)
                dedup.append(t)
        tracker.ports[port_name] = dedup
    tracker.port_box_specs.clear()


# ---------------------------------------------------------------------------
# 计算 chip XY bounding box (替代 BoundsForPathAndPolyTables)
# ---------------------------------------------------------------------------

def compute_chip_bbox_si(components: list[ComponentIR],
                         side_buffer_si: float) -> tuple[float, float, float, float]:
    """从所有 primitive 的 shapely union 算 (xmin, ymin, xmax, ymax), 单位 SI 米。

    side_buffer_si 沿四周扩张。
    """
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for component in components:
        for primitive in component.primitives:
            if primitive.helper:
                continue
            if primitive.kind in {"path", "junction"} and primitive.width is not None:
                x0, y0, x1, y1 = primitive.geometry.buffer(primitive.width / 2).bounds
            else:
                x0, y0, x1, y1 = primitive.geometry.bounds
            minx = min(minx, x0)
            miny = min(miny, y0)
            maxx = max(maxx, x1)
            maxy = max(maxy, y1)
    if not np.isfinite(minx):
        raise ValueError("Design has no primitives to compute bbox from")
    return (
        minx * 1e-3 - side_buffer_si,
        miny * 1e-3 - side_buffer_si,
        maxx * 1e-3 + side_buffer_si,
        maxy * 1e-3 + side_buffer_si,
    )
