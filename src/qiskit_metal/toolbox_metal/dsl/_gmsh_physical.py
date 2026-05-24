# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter: 阶段 F — physical group 命名 + 注册。

把 fragment 后的 `GeomTracker` 内容映射到 gmsh physical group。命名规则
集中在 ``PHYSICAL_GROUP_NAMING`` 字典中, 让 M4 (端口 / 对称面) 不必改命名
层即可扩展。

plan §3.3-F + §6 命名约定:
    metal layer ground volume    → ``gnd_layer{N}``      (dim=3)
    metal layer ground 外表面    → ``gnd_layer{N}_sfs``  (dim=2)
    dielectric layer volume      → ``substrate_layer{N}`` (dim=3)
    component poly/path volume   → ``{component}_{primitive}``      (dim=3)
    component poly/path 外表面   → ``{component}_{primitive}_sfs``  (dim=2)
    junction surface             → ``{component}_{primitive}``      (dim=2)
    真空体                       → ``vacuum``            (dim=3)
    真空外边界                   → ``vacuum_outer``      (dim=2)

命名硬约束 (plan §6): 满足 ``^[A-Za-z][A-Za-z0-9_]*$``。adapter 自带
``_sanitize`` 把 ``.`` / ``-`` / 空格 / 数字开头等情况转 ``_``。重名直接
``raise``, 不静默叠加。

允许 import:
- `gmsh`
- 标准库
- 本包 ``_gmsh_geometry.GeomTracker``

deny-list (硬性): 同 `_gmsh_geometry.py` 顶部说明。
"""

from __future__ import annotations

import re
from typing import Optional

from ._gmsh_geometry import GeomTracker

try:
    import gmsh
except ImportError:  # pragma: no cover
    gmsh = None


# 命名常量, 供 M4 端口 / 对称面命名时复用 (reviewer2 前置预期 #2)。
PHYSICAL_GROUP_NAMING = {
    "ground_volume": "gnd_layer{layer}",
    "ground_surface": "gnd_layer{layer}_sfs",
    "substrate_volume": "substrate_layer{layer}",
    "component_volume": "{component}_{primitive}",
    "component_surface": "{component}_{primitive}_sfs",
    "junction_surface": "{component}_{primitive}_jj",
    "vacuum_volume": "vacuum",
    "vacuum_outer": "vacuum_outer",
    "port_lumped": "port_{component}_{pin}",
    "port_ground": "port_{component}_{pin}_gnd",
    "symmetry_surface": "symmetry_{plane}",
}


_INVALID_NAME_CHAR_RE = re.compile(r"[^A-Za-z0-9_]")


def _sanitize(name: str) -> str:
    """把 ``Q1.bus.pad_left`` 之类的名字转成 gmsh 兼容标识符。

    步骤: 非 ``[A-Za-z0-9_]`` 字符替换成 ``_``; 若结果以数字开头, 加前导
    ``g_``; 空串退化成 ``unnamed``。
    """
    cleaned = _INVALID_NAME_CHAR_RE.sub("_", name)
    if not cleaned:
        return "unnamed"
    if cleaned[0].isdigit():
        cleaned = "g_" + cleaned
    return cleaned


class _GroupRegistry:
    """记录已分配的 physical group, 防重名 + 收集为 `physical_groups` 出参。"""

    def __init__(self) -> None:
        self._taken: dict[str, tuple[int, list[int]]] = {}

    def add(self, name: str, dim: int, tags: list[int]) -> None:
        if not tags:
            return
        sane = _sanitize(name)
        if sane in self._taken:
            raise ValueError(
                f"physical group name {sane!r} reused (already assigned with "
                f"dim={self._taken[sane][0]})")
        gmsh.model.addPhysicalGroup(dim=dim, tags=tags, tag=-1, name=sane)
        self._taken[sane] = (dim, list(tags))

    def as_dict(self) -> dict[str, tuple[int, list[int]]]:
        return dict(self._taken)


# ---------------------------------------------------------------------------
# 出表面 helpers
# ---------------------------------------------------------------------------

def _surface_tags_of(volume_tags: list[int]) -> list[int]:
    """getBoundary([(3,v),...]) 取所有边界 face (dim=2) 的 tag, 去重保序。"""
    if not volume_tags:
        return []
    boundary = gmsh.model.getBoundary(
        [(3, t) for t in volume_tags],
        combined=False, oriented=False, recursive=False)
    seen: dict[int, None] = {}
    for dim, tag in boundary:
        if dim == 2:
            seen.setdefault(abs(int(tag)), None)
    return list(seen.keys())


# ---------------------------------------------------------------------------
# Stage F 主入口
# ---------------------------------------------------------------------------

def _collect_symmetry_face_tags(tracker: GeomTracker, plane: str,
                                tol: float = 1e-7) -> list[int]:
    """筛出所有体边界面中, 中心位于对称平面上 (x=0/y=0/z=0) 的 face。

    plane='y0' → 筛 face center 的 y ≈ 0; 类似 x0/z0。
    """
    axis = {"x0": 0, "y0": 1, "z0": 2}.get(plane)
    if axis is None:
        return []
    targets: list[int] = []
    for layer_tags in tracker.layer_ground.values():
        targets.extend(layer_tags)
    for layer_dict in (tracker.polys, tracker.paths):
        for named in layer_dict.values():
            for tags in named.values():
                targets.extend(tags)
    if tracker.vacuum_box is not None:
        targets.append(tracker.vacuum_box)
    if not targets:
        return []
    boundary = gmsh.model.getBoundary(
        [(3, t) for t in targets],
        combined=False, oriented=False, recursive=False)
    seen: dict[int, None] = {}
    for dim, tag in boundary:
        if dim != 2:
            continue
        face_tag = abs(int(tag))
        if face_tag in seen:
            continue
        fc = gmsh.model.occ.getCenterOfMass(2, face_tag)
        if abs(fc[axis]) < tol:
            # Also check that the face normal is aligned with the symmetry axis.
            # getNormal returns (nx, ny, nz) at parametric coordinate (0, 0).
            try:
                nx, ny, nz = gmsh.model.getNormal(face_tag, [0.0, 0.0])
                normal = [nx, ny, nz]
                # The symmetry face normal must be ≈ ±e_axis; other two components ≈ 0.
                other_axes = [i for i in range(3) if i != axis]
                if all(abs(normal[i]) < 0.1 for i in other_axes):
                    seen[face_tag] = None
            except Exception:
                # If normal query fails, fall back to centroid-only check.
                seen[face_tag] = None
    return list(seen.keys())


def assign_physical_groups(tracker: GeomTracker,
                           layer_stack_si: dict[int, dict],
                           symmetry_specs=None
                           ) -> dict[str, tuple[int, list[int]]]:
    """注册所有 physical group, 返回 ``{name: (dim, [tags])}`` 字典。

    调用顺序固定: layers → components → JJ → vacuum → ports →
    symmetry。port / symmetry 模板从 `PHYSICAL_GROUP_NAMING` 取。
    """
    if gmsh is None:
        raise ImportError("gmsh required for assign_physical_groups")
    registry = _GroupRegistry()

    # 1) layer ground / substrate
    for layer, spec in layer_stack_si.items():
        tags = tracker.layer_ground.get(layer, [])
        kind = spec.get("kind", "metal")
        if not tags:
            continue
        if kind == "metal":
            vol_name = PHYSICAL_GROUP_NAMING["ground_volume"].format(layer=layer)
            sfs_name = PHYSICAL_GROUP_NAMING["ground_surface"].format(layer=layer)
            registry.add(vol_name, dim=3, tags=tags)
            registry.add(sfs_name, dim=2, tags=_surface_tags_of(tags))
        else:  # dielectric
            vol_name = PHYSICAL_GROUP_NAMING["substrate_volume"].format(
                layer=layer)
            registry.add(vol_name, dim=3, tags=tags)

    # 2) component polys / paths (3D volume + 外表面)
    for layer_dict in (tracker.polys, tracker.paths):
        for layer, named in layer_dict.items():
            for (component, primitive), tags in named.items():
                vol_name = PHYSICAL_GROUP_NAMING["component_volume"].format(
                    component=component, primitive=primitive)
                sfs_name = PHYSICAL_GROUP_NAMING["component_surface"].format(
                    component=component, primitive=primitive)
                registry.add(vol_name, dim=3, tags=tags)
                registry.add(sfs_name, dim=2, tags=_surface_tags_of(tags))

    # 3) JJ surfaces (2D, 不 extrude)
    for layer, named in tracker.juncs.items():
        for (component, primitive), tags in named.items():
            name = PHYSICAL_GROUP_NAMING["junction_surface"].format(
                component=component, primitive=primitive)
            registry.add(name, dim=2, tags=tags)

    # 4) vacuum 体 + 外边界面
    if tracker.vacuum_box is not None:
        vac_name = PHYSICAL_GROUP_NAMING["vacuum_volume"]
        outer_name = PHYSICAL_GROUP_NAMING["vacuum_outer"]
        registry.add(vac_name, dim=3, tags=[tracker.vacuum_box])
        registry.add(outer_name, dim=2,
                     tags=_surface_tags_of([tracker.vacuum_box]))

    # 5) 端口面 (M4): tracker.ports 由 `resolve_port_surfaces` 在 cut
    # 之后填好。端口元数据 (`is_lumped` 等) 在 stage B' 时由
    # `_stage_endcaps_and_ports` 写入 `tracker.port_metadata` (port_name →
    # {component, pin, is_lumped}); 缺省按 lumped。
    for port_name, tags in tracker.ports.items():
        if not tags:
            continue
        meta = tracker.port_metadata.get(port_name, {})
        is_lumped = meta.get("is_lumped", True)
        template_key = "port_lumped" if is_lumped else "port_ground"
        full_name = PHYSICAL_GROUP_NAMING[template_key].format(
            component=meta.get("component", "unknown"),
            pin=meta.get("pin", port_name))
        registry.add(full_name, dim=2, tags=tags)

    # 6) 对称面 (M4): apply_symmetry_cuts 已经把对称面留在了 ground/
    # vacuum 表面上, 这里按 plane=0 筛出 face center 落在平面上的面。
    if symmetry_specs:
        for spec in symmetry_specs:
            plane = spec["plane"]
            tags = _collect_symmetry_face_tags(tracker, plane)
            if tags:
                name = PHYSICAL_GROUP_NAMING["symmetry_surface"].format(
                    plane=plane)
                registry.add(name, dim=2, tags=tags)

    return registry.as_dict()
