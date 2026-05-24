# -*- coding: utf-8 -*-
"""DSL → Gmsh adapter: 阶段 G — size fields + generate(3) + write。

输入: ``GeomTracker`` (fragment 之后) + ``options.mesh`` (SI 米); 调用方
负责保证已 ``occ.synchronize()``。

算法照 `gmsh_renderer.py:define_mesh_size_fields` (1082-1196) 思路:
- 收集所有导体外表面 (component poly/path volume + metal layer ground
  volume 的边界面 + junction 2D surface) 的 curve, 用 ``Distance`` field
  作为基础;
- ``Threshold`` field 在 ``DistMin`` 与 ``DistMax`` 之间从 ``SizeMin``
  渐变到 ``SizeMax``; JJ 单独一组 Threshold (更小的 SizeMin);
- ``Min`` field 合并所有 Threshold, 设为 background mesh。

所有长度参数 SI 米; 与 plan §5 对齐。

允许 import:
- `gmsh`
- 标准库
- 本包 ``_gmsh_geometry.GeomTracker``

deny-list (硬性): 同其它 `_gmsh_*.py`。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from ._gmsh_geometry import GeomTracker

logger = logging.getLogger(__name__)

try:
    import gmsh
except ImportError:  # pragma: no cover
    gmsh = None


# 默认 mesh 参数 (SI 米); 与 plan §3.1 demo schema 数值对齐 (`max_size: 70um`,
# `min_size: 5um`, `max_size_jj: 5um`, conductor_refine min/max = 10um/130um)。
DEFAULT_MESH_SI: dict[str, Any] = {
    "max_size": 70e-6,
    "min_size": 5e-6,
    "max_size_jj": 5e-6,
    "conductor_refine": {"min_dist": 10e-6, "max_dist": 130e-6},
}


def _resolve_mesh_options(mesh_opts: dict[str, Any]) -> dict[str, Any]:
    """合并用户 mesh 选项与默认值 (SI), 返回完整字典。"""
    out: dict[str, Any] = dict(DEFAULT_MESH_SI)
    out.update({k: v for k, v in mesh_opts.items() if k != "conductor_refine"})
    refine = dict(DEFAULT_MESH_SI["conductor_refine"])
    if "conductor_refine" in mesh_opts and mesh_opts["conductor_refine"]:
        refine.update(mesh_opts["conductor_refine"])
    out["conductor_refine"] = refine
    return out


def _curves_of_surfaces(surface_tags: list[int]) -> list[int]:
    """从 surface tag 列表展开所有 curve (dim=1) tag, 去重。"""
    seen: dict[int, None] = {}
    for surf in surface_tags:
        try:
            cl = gmsh.model.occ.getCurveLoops(surf)
        except Exception as exc:
            logger.warning("Could not get curve loops for surface %d: %s", surf, exc)
            continue
        # cl = (loop_tags, [[curve_tag, ...], ...])
        for loop_curves in cl[1]:
            for c in loop_curves:
                seen.setdefault(abs(int(c)), None)
    return list(seen.keys())


def _conductor_surface_tags(tracker: GeomTracker,
                            layer_stack_si: dict[int, dict]) -> list[int]:
    """收集所有导体外表面 (component volume 的 face + metal layer ground 的 face)。"""
    volumes: list[int] = []
    for layer_dict in (tracker.polys, tracker.paths):
        for named in layer_dict.values():
            for tags in named.values():
                volumes.extend(tags)
    for layer, spec in layer_stack_si.items():
        if spec.get("kind") == "metal":
            volumes.extend(tracker.layer_ground.get(layer, []))

    if not volumes:
        return []
    boundary = gmsh.model.getBoundary(
        [(3, t) for t in volumes],
        combined=False, oriented=False, recursive=False)
    seen: dict[int, None] = {}
    for dim, tag in boundary:
        if dim == 2:
            seen.setdefault(abs(int(tag)), None)
    return list(seen.keys())


def _junction_surface_tags(tracker: GeomTracker) -> list[int]:
    out: list[int] = []
    for named in tracker.juncs.values():
        for tags in named.values():
            out.extend(tags)
    return out


def define_size_fields(tracker: GeomTracker,
                       layer_stack_si: dict[int, dict],
                       mesh_opts: dict[str, Any]) -> None:
    """注册 distance + threshold + min fields, 设为 background mesh。"""
    if gmsh is None:
        raise ImportError("gmsh required for define_size_fields")
    opts = _resolve_mesh_options(mesh_opts)
    size_min = float(opts["min_size"])
    size_max = float(opts["max_size"])
    size_min_jj = float(opts["max_size_jj"])
    dist_min = float(opts["conductor_refine"]["min_dist"])
    dist_max = float(opts["conductor_refine"]["max_dist"])

    threshold_fields: list[int] = []

    # 导体 (含 ground / pads / paths) 边缘细化
    cond_surfaces = _conductor_surface_tags(tracker, layer_stack_si)
    cond_curves = _curves_of_surfaces(cond_surfaces)
    if cond_curves:
        df = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(df, "CurvesList", cond_curves)
        gmsh.model.mesh.field.setNumber(df, "NumPointsPerCurve", 100)
        tf = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(tf, "InField", df)
        gmsh.model.mesh.field.setNumber(tf, "DistMin", dist_min)
        gmsh.model.mesh.field.setNumber(tf, "DistMax", dist_max)
        gmsh.model.mesh.field.setNumber(tf, "SizeMin", size_min)
        gmsh.model.mesh.field.setNumber(tf, "SizeMax", size_max)
        gmsh.model.mesh.field.setNumber(tf, "Sigmoid", 1)
        threshold_fields.append(tf)

    # JJ 局部细化 (用 surface 的 curve)
    jj_surfaces = _junction_surface_tags(tracker)
    jj_curves = _curves_of_surfaces(jj_surfaces)
    if jj_curves:
        jj_df = gmsh.model.mesh.field.add("Distance")
        gmsh.model.mesh.field.setNumbers(jj_df, "CurvesList", jj_curves)
        gmsh.model.mesh.field.setNumber(jj_df, "NumPointsPerCurve", 100)
        jj_tf = gmsh.model.mesh.field.add("Threshold")
        gmsh.model.mesh.field.setNumber(jj_tf, "InField", jj_df)
        gmsh.model.mesh.field.setNumber(jj_tf, "DistMin", dist_min)
        gmsh.model.mesh.field.setNumber(jj_tf, "DistMax", dist_max)
        gmsh.model.mesh.field.setNumber(jj_tf, "SizeMin", size_min_jj)
        gmsh.model.mesh.field.setNumber(jj_tf, "SizeMax", size_max)
        gmsh.model.mesh.field.setNumber(jj_tf, "Sigmoid", 1)
        threshold_fields.append(jj_tf)

    if threshold_fields:
        min_field = gmsh.model.mesh.field.add("Min")
        gmsh.model.mesh.field.setNumbers(min_field, "FieldsList",
                                         threshold_fields)
        gmsh.model.mesh.field.setAsBackgroundMesh(min_field)
        gmsh.option.setNumber("Mesh.MeshSizeExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        # M5 (M3 r1 建议 4): MeshSizeMin/Max 只在有 size field 时设, 无导体
        # 也无 JJ 的极端 design 走 gmsh 全默认 size, 避免误用 user kwarg。
        gmsh.option.setNumber("Mesh.MeshSizeMin", size_min)
        gmsh.option.setNumber("Mesh.MeshSizeMax", size_max)


def generate_mesh(dim: int = 3) -> None:
    if gmsh is None:
        raise ImportError("gmsh required for generate_mesh")
    gmsh.model.mesh.generate(dim)


_KNOWN_FORMATS = {"msh4", "msh2", "vtk", "stl", "step", "iges", "brep", "pos"}


def write_mesh(output_path: Path, output_format: str = "msh4",
               output_scaling: float = 1.0) -> Path:
    """写出 ``.msh`` (默认 msh4 ASCII)。

    output_scaling 直接给 ``Mesh.ScalingFactor``; SI 输出默认 1.0 (plan §5)。
    """
    if gmsh is None:
        raise ImportError("gmsh required for write_mesh")
    if output_format not in _KNOWN_FORMATS:
        raise ValueError(
            f"Unknown output format {output_format!r}; "
            f"known: {sorted(_KNOWN_FORMATS)}")
    gmsh.option.setNumber("Mesh.ScalingFactor", float(output_scaling))
    if output_format == "msh4":
        gmsh.option.setNumber("Mesh.MshFileVersion", 4.1)
    elif output_format == "msh2":
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gmsh.write(str(output_path))
    return output_path
