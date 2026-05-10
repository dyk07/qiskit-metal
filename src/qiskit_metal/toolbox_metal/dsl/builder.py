# -*- coding: utf-8 -*-
"""Native YAML DSL for Hamiltonian-Circuit-Netlist-Geometry designs.

This module intentionally does not instantiate qlibrary components such as
``TransmonPocket`` or ``RouteMeander``.  The YAML file is first resolved into a
small design IR, then optionally exported to a regular Metal ``QDesign`` by
writing primitive shapely geometry, pins, and net connections directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import math
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Optional, Union

import numpy as np
import shapely.affinity
from shapely.geometry import LineString, Polygon
import yaml

from qiskit_metal import Dict
from qiskit_metal import draw
from qiskit_metal.qlibrary.core.base import QComponent

from ._helpers import (
    UniqueKeyYamlLoader as _UniqueKeyLoader,
    deep_merge as _deep_merge,
    parse_angle as _parse_angle,
    parse_bool as _as_bool,
    parse_number as _parse_number,
    parse_optional_number as _parse_optional_number,
    parse_point as _parse_point,
    parse_points as _parse_points,
    reject_unknown_keys as _reject_unknown_keys,
)
from .component_templates import expand_component_template
from .errors import DesignDslError
from .expression import (
    evaluate_expression as _evaluate_expression,
    walk_substitute as _walk_substitute,
)
from .geometry_ops import (
    evaluate_geometry_operations,
    resolve_operation_reference,
)
from .template_registry import ComponentTemplateRegistry

__all__ = [
    "DesignDslError",
    "DesignIR",
    "PrimitiveIR",
    "PinIR",
    "ComponentIR",
    "NativeComponent",
    "BUILTIN_DESIGNS",
    "build_ir",
    "export_ir_to_metal",
    "build_design",
    "register_design",
    "clear_user_registry",
]


CURRENT_SCHEMA = "qiskit-metal/design-dsl/3"

ROOT_KEYS = {
    "schema", "vars", "hamiltonian", "circuit", "netlist", "geometry",
    "templates",
}
GEOMETRY_KEYS = {"design", "templates", "components", "transforms"}
DESIGN_KEYS = {
    "class", "metadata", "overwrite_enabled", "enable_renderers", "variables",
    "chip",
}
TRANSFORM_KEYS = {"translate", "rotate", "origin"}
COMPONENT_KEYS = {
    "name", "primitives", "pins", "metadata", "transform", "translate",
    "rotate", "origin", "type", "options", "operations", "generators",
}
PRIMITIVE_KEYS = {
    "name", "kind", "shape", "type", "primitive", "points", "center", "size",
    "subtract", "helper", "layer", "chip", "width", "fillet", "transform",
    "operation",
}
PIN_KEYS = {
    "name", "points", "width", "gap", "chip", "transform", "mode",
    "from_operation", "operation", "segment",
}
GENERATOR_KEYS = {"for_each", "as", "operations", "primitives", "pins"}
NETLIST_KEYS = {"connections"}
NETLIST_CONNECTION_KEYS = {"from", "to"}
CHIP_KEYS = {
    "name", "size", "size_x", "size_y", "size_z", "center_x", "center_y",
    "center_z",
}
CHIP_SIZE_KEYS = {"size_x", "size_y"}


BUILTIN_DESIGNS: dict[str, str] = {
    "DesignPlanar": "qiskit_metal.designs.design_planar.DesignPlanar",
    "DesignFlipChip": "qiskit_metal.designs.design_flipchip.DesignFlipChip",
    "DesignMultiPlanar":
        "qiskit_metal.designs.design_multiplanar.MultiPlanar",
}

_USER_DESIGNS: dict[str, Any] = {}


@dataclass
class PrimitiveIR:
    """A resolved geometry primitive in Metal user units."""

    component: str
    name: str
    kind: str
    shape: str
    geometry: Any
    subtract: bool = False
    helper: bool = False
    layer: int = 1
    chip: str = "main"
    width: Optional[float] = None
    fillet: Optional[float] = None
    options: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class PinIR:
    """A resolved Metal pin."""

    component: str
    name: str
    points: list[list[float]]
    width: float
    gap: Optional[float] = None
    chip: str = "main"
    input_as_norm: bool = False
    normal_points: Optional[list[list[float]]] = None
    source: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.normal_points is None:
            self.normal_points = self.points


@dataclass
class ComponentIR:
    """A component container made only from primitives and pins."""

    name: str
    primitives: list[PrimitiveIR] = field(default_factory=list)
    pins: list[PinIR] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    type: Optional[str] = None
    options: dict[str, Any] = field(default_factory=dict)
    template: Optional[str] = None
    inherited: list[str] = field(default_factory=list)
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class DesignIR:
    """Resolved v3 design IR."""

    schema: str
    vars: dict[str, Any]
    hamiltonian: Any
    circuit: Any
    netlist: Any
    design: dict[str, Any]
    components: list[ComponentIR]
    geometry: dict[str, Any]
    derived: dict[str, Any]

    def to_metadata(self) -> dict[str, Any]:
        """Return a metadata-safe snapshot of the IR."""
        return {
            "schema": self.schema,
            "vars": self.vars,
            "hamiltonian": self.hamiltonian,
            "circuit": self.circuit,
            "netlist": self.netlist,
            "design": self.design,
            "geometry": self.geometry,
            "derived": self.derived,
        }


class NativeComponent(QComponent):
    """Minimal Metal component used only to own native DSL geometry."""

    component_metadata = Dict(short_name="N",
                              _qgeometry_table_path="True",
                              _qgeometry_table_poly="True",
                              _qgeometry_table_junction="True")
    TOOLTIP = "Native primitive component"

    def make(self):
        """Native components are populated by the DSL exporter."""


def register_design(short_name: str, cls_or_path: Union[type, str]) -> None:
    """Register a QDesign subclass short name for the native DSL."""
    _USER_DESIGNS[short_name] = cls_or_path


def clear_user_registry() -> None:
    """Clear user registered design classes."""
    _USER_DESIGNS.clear()


def _resolve_class(name_or_path: str, table: Mapping[str, Any],
                   user_table: Mapping[str, Any], kind: str):
    if not isinstance(name_or_path, str) or not name_or_path:
        raise DesignDslError(f"{kind} class must be a non-empty string")

    target = user_table.get(name_or_path) or table.get(name_or_path) or name_or_path
    if not isinstance(target, str):
        return target
    if "." not in target:
        raise DesignDslError(f"Unknown {kind} short name: {name_or_path!r}")

    module_path, attr_name = target.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise DesignDslError(
            f"Cannot import {kind} module {module_path!r}: {exc}") from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise DesignDslError(
            f"Module {module_path!r} has no {kind} class {attr_name!r}") from exc


def _load_yaml(source: Union[str, Path]) -> tuple[dict, Optional[Path]]:
    if isinstance(source, Path):
        return _load_yaml_file(source)

    if isinstance(source, str):
        candidate = Path(source)
        if "\n" not in source and len(source) < 4096 and candidate.exists():
            return _load_yaml_file(candidate)
        try:
            data = yaml.load(source, Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise DesignDslError(f"YAML parse failed: {exc}") from exc
        if not isinstance(data, dict):
            raise DesignDslError("DSL document must be a mapping")
        return data, None

    raise DesignDslError(
        f"build_ir accepts Path or str, got {type(source).__name__}")


def _load_yaml_file(path: Path) -> tuple[dict, Path]:
    if not path.exists():
        raise DesignDslError(f"DSL file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise DesignDslError(f"YAML parse failed ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise DesignDslError(f"DSL document must be a mapping ({path})")
    return data, path.parent


def _expand_includes(node: Any,
                     base_dir: Optional[Path],
                     seen: Optional[frozenset[Path]] = None) -> Any:
    seen = seen or frozenset()
    if isinstance(node, dict):
        if set(node.keys()) == {"$include"}:
            include_path = node["$include"]
            if not isinstance(include_path, str):
                raise DesignDslError("$include value must be a string path")
            if base_dir is None:
                raise DesignDslError(
                    "$include requires build_ir to receive a file path")
            target = (base_dir / include_path).resolve()
            if target in seen:
                chain = " -> ".join(str(path) for path in [*seen, target])
                raise DesignDslError(f"$include cycle detected: {chain}")
            included, child_dir = _load_yaml_file(target)
            return _expand_includes(included, child_dir, seen | {target})
        return {
            key: _expand_includes(val, base_dir, seen)
            for key, val in node.items()
        }
    if isinstance(node, list):
        return [_expand_includes(item, base_dir, seen) for item in node]
    return node


def _resolve_template(name: str, templates: Mapping[str, Any],
                      seen: frozenset[str]) -> dict:
    if name in seen:
        raise DesignDslError(f"$extend cycle detected at {name!r}")
    if name not in templates:
        raise DesignDslError(
            f"Unknown template {name!r}; known templates: {sorted(templates)}")
    template = templates[name]
    if not isinstance(template, dict):
        raise DesignDslError(f"Template {name!r} must be a mapping")
    if "$extend" in template:
        parent_name = template["$extend"]
        if not isinstance(parent_name, str):
            raise DesignDslError(
                f"Template {name!r} $extend value must be a template name")
        parent = _resolve_template(parent_name, templates, seen | {name})
        body = {key: val for key, val in template.items() if key != "$extend"}
        return _deep_merge(parent, body)
    return dict(template)


def _expand_node(node: Any, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list[Any]:
    if not isinstance(node, dict):
        return [_walk_substitute(node, ctx)]

    if "$for" in node:
        iter_list = node["$for"]
        if not isinstance(iter_list, list):
            raise DesignDslError("$for value must be a list")
        body = {key: val for key, val in node.items() if key != "$for"}
        results: list[Any] = []
        for index, iter_vars in enumerate(iter_list):
            if not isinstance(iter_vars, dict):
                raise DesignDslError(f"$for[{index}] must be a mapping")
            resolved_iter = _walk_substitute(iter_vars, ctx)
            results.extend(
                _expand_node(body, {**ctx, **resolved_iter}, templates))
        return results

    if "$extend" in node:
        template_name = node["$extend"]
        if not isinstance(template_name, str):
            raise DesignDslError("$extend value must be a template name")
        template = _resolve_template(template_name, templates, frozenset())
        body = {key: val for key, val in node.items() if key != "$extend"}
        return _expand_node(_deep_merge(template, body), ctx, templates)

    return [_walk_substitute(node, ctx)]


def _expand_list(items: list, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list:
    if not isinstance(items, list):
        raise DesignDslError("Expandable DSL field must be a list")
    out: list[Any] = []
    for item in items:
        out.extend(_expand_node(item, ctx, templates))
    return out


def _optional_mapping(container: Mapping[str, Any], key: str) -> dict:
    if key not in container:
        return {}
    value = container[key]
    if not isinstance(value, Mapping):
        raise DesignDslError(f"{key} must be a mapping")
    return dict(value)


def _optional_list(container: Mapping[str, Any], key: str) -> list:
    if key not in container:
        return []
    value = container[key]
    if not isinstance(value, list):
        raise DesignDslError(f"{key} must be a list")
    return value


def _validate_transform(transform: Mapping[str, Any], owner: str) -> dict[str, Any]:
    out = dict(transform)
    unknown = set(out) - TRANSFORM_KEYS
    if unknown:
        raise DesignDslError(
            f"Unknown transform key(s) for {owner}: {sorted(unknown)}")
    return out


def _parse_type(spec: Mapping[str, Any]) -> tuple[str, str]:
    type_value = spec.get("type") or spec.get("primitive")
    if type_value:
        if not isinstance(type_value, str) or "." not in type_value:
            raise DesignDslError(
                "primitive type must look like 'poly.rectangle'")
        kind, shape = type_value.split(".", 1)
        return kind, shape

    kind = spec.get("kind")
    shape = spec.get("shape")
    if not kind or not shape:
        raise DesignDslError("Primitive requires either type or kind + shape")
    return str(kind), str(shape)


def _layer(value: Any, owner: str = "layer") -> int:
    if value is None:
        return 1
    if isinstance(value, bool):
        raise DesignDslError(f"{owner} must be an integer, got {value!r}")
    try:
        if isinstance(value, str):
            return int(float(value.strip()))
        return int(value)
    except (TypeError, ValueError) as exc:
        raise DesignDslError(
            f"{owner} must be an integer, got {value!r}") from exc


def _transform_spec(component_spec: Mapping[str, Any],
                    geometry_spec: Mapping[str, Any],
                    component_name: str) -> dict[str, Any]:
    transforms = geometry_spec.get("transforms", {})
    transform = {}
    if isinstance(transforms, Mapping):
        raw_transform = transforms.get(component_name)
        if raw_transform is not None:
            if not isinstance(raw_transform, Mapping):
                raise DesignDslError(
                    f"geometry.transforms.{component_name} must be a mapping")
            transform = dict(raw_transform)
    transform = _deep_merge(transform, _optional_mapping(component_spec, "transform"))
    for key in ("translate", "rotate", "origin"):
        if key in component_spec:
            transform[key] = component_spec[key]
    return _validate_transform(transform, component_name)


def _apply_transform_to_geometry(geometry: Any,
                                 transform: Mapping[str, Any],
                                 variables: Mapping[str, Any],
                                 owner: str = "transform") -> Any:
    origin = _parse_point(transform.get("origin", [0, 0]), variables,
                          f"{owner}.origin")
    rotate = _parse_angle(transform.get("rotate", 0), f"{owner}.rotate")
    translate = transform.get("translate", [0, 0])

    result = geometry
    if rotate:
        result = shapely.affinity.rotate(result, rotate, origin=tuple(origin))
    if translate:
        xoff, yoff = _parse_point(translate, variables, f"{owner}.translate")
        result = shapely.affinity.translate(result, xoff=xoff, yoff=yoff)
    return result


def _rotate_point(point: list[float], angle_deg: float,
                  origin: list[float]) -> list[float]:
    if not angle_deg:
        return list(point)
    angle = math.radians(angle_deg)
    x, y = point[0] - origin[0], point[1] - origin[1]
    return [
        origin[0] + x * math.cos(angle) - y * math.sin(angle),
        origin[1] + x * math.sin(angle) + y * math.cos(angle),
    ]


def _apply_transform_to_points(points: list[list[float]],
                               transform: Mapping[str, Any],
                               variables: Mapping[str, Any],
                               owner: str = "transform") -> list[list[float]]:
    origin = _parse_point(transform.get("origin", [0, 0]), variables,
                          f"{owner}.origin")
    rotate = _parse_angle(transform.get("rotate", 0), f"{owner}.rotate")
    translate = _parse_point(transform.get("translate", [0, 0]), variables,
                             f"{owner}.translate")
    out = []
    for point in points:
        rotated = _rotate_point(point, rotate, origin)
        out.append([rotated[0] + translate[0], rotated[1] + translate[1]])
    return out


def _make_primitive_geometry(spec: Mapping[str, Any],
                             kind: str,
                             shape: str,
                             variables: Mapping[str, Any],
                             operations: Optional[Mapping[str, Any]] = None,
                             owner: str = "primitive") -> Any:
    if shape == "from_operation":
        if "operation" not in spec:
            raise DesignDslError(
                f"{kind}.from_operation requires operation")
        geometry = resolve_operation_reference(operations or {},
                                               spec["operation"],
                                               f"primitive {kind}.{shape}")
        if not hasattr(geometry, "geom_type"):
            raise DesignDslError(
                f"{kind}.from_operation source must resolve to shapely geometry")
        if kind == "poly" and not isinstance(geometry, Polygon):
            raise DesignDslError(
                f"poly.from_operation source must resolve to a Polygon")
        if kind in {"path", "junction"} and not isinstance(geometry, LineString):
            raise DesignDslError(
                f"{kind}.from_operation source must resolve to a LineString")
        return geometry

    if kind == "poly" and shape == "rectangle":
        center = _parse_point(spec.get("center", [0, 0]), variables,
                              f"{owner}.center")
        size = spec.get("size")
        if not isinstance(size, list) or len(size) != 2:
            raise DesignDslError("poly.rectangle requires size: [width, height]")
        width = _parse_number(size[0], variables, f"{owner}.size[0]")
        height = _parse_number(size[1], variables, f"{owner}.size[1]")
        x0, y0 = center[0] - width / 2.0, center[1] - height / 2.0
        x1, y1 = center[0] + width / 2.0, center[1] + height / 2.0
        return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    if kind == "poly" and shape == "polygon":
        return Polygon(_parse_points(spec.get("points"), variables,
                                     f"{owner}.points"))

    if kind == "path" and shape in {"line", "polyline"}:
        return LineString(_parse_points(spec.get("points"), variables,
                                        f"{owner}.points"))

    if kind == "junction" and shape == "line":
        points = _parse_points(spec.get("points"), variables,
                               f"{owner}.points")
        if len(points) != 2:
            raise DesignDslError("junction.line requires exactly two points")
        return LineString(points)

    raise DesignDslError(f"Unsupported primitive type: {kind}.{shape}")


def _primitive_from_spec(component_name: str, spec: Mapping[str, Any],
                         transform: Mapping[str, Any],
                         variables: Mapping[str, Any],
                         operations: Optional[Mapping[str, Any]] = None) -> PrimitiveIR:
    if not isinstance(spec, Mapping):
        raise DesignDslError(
            f"Primitive in {component_name!r} must be a mapping")
    if "class" in spec:
        raise DesignDslError(
            "v3 native geometry does not accept qlibrary class entries")
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"Primitive in {component_name!r} requires name")
    _reject_unknown_keys(spec, PRIMITIVE_KEYS,
                         f"primitive {component_name}.{name}")

    kind, shape = _parse_type(spec)
    geometry = _make_primitive_geometry(spec, kind, shape, variables,
                                        operations,
                                        f"primitive {component_name}.{name}")
    merged_transform = _deep_merge(
        transform,
        _validate_transform(_optional_mapping(spec, "transform"),
                            f"{component_name}.{name}"),
    )
    geometry = _apply_transform_to_geometry(
        geometry, merged_transform, variables,
        f"primitive {component_name}.{name}.transform")

    width = _parse_optional_number(spec.get("width"), variables,
                                   f"primitive {component_name}.{name}.width")
    fillet = _parse_optional_number(spec.get("fillet"), variables,
                                    f"primitive {component_name}.{name}.fillet")
    if kind in {"path", "junction"} and width is None:
        raise DesignDslError(f"{kind}.{shape} primitive {component_name}.{name} "
                             "requires width")

    return PrimitiveIR(component=component_name,
                       name=name,
                       kind=kind,
                       shape=shape,
                       geometry=geometry,
                       subtract=_as_bool(spec.get("subtract", False),
                                         f"{component_name}.{name}.subtract"),
                       helper=_as_bool(spec.get("helper", False),
                                       f"{component_name}.{name}.helper"),
                       layer=_layer(spec.get("layer"),
                                    f"primitive {component_name}.{name}.layer"),
                       chip=str(spec.get("chip", "main")),
                       width=width,
                       fillet=fillet,
                       options={},
                       source=dict(spec))


def _points_from_normal_segment(component_name: str, name: str,
                                spec: Mapping[str, Any],
                                variables: Mapping[str, Any],
                                operations: Mapping[str, Any]
                                ) -> list[list[float]]:
    operation = spec.get("from_operation", spec.get("operation"))
    if operation is None:
        raise DesignDslError(
            f"Pin {component_name}.{name} normal_segment requires "
            "from_operation")
    if spec.get("segment", "last") != "last":
        raise DesignDslError(
            f"Pin {component_name}.{name} normal_segment only supports "
            "segment: last")
    geometry = resolve_operation_reference(operations, operation,
                                           f"pin {component_name}.{name}")
    if not isinstance(geometry, LineString):
        raise DesignDslError(
            f"Pin {component_name}.{name} normal_segment source must resolve "
            "to a LineString")
    coords = list(geometry.coords)
    if len(coords) < 2:
        raise DesignDslError(
            f"Pin {component_name}.{name} normal_segment source must contain "
            "at least two points")

    normal_points = [
        _parse_point(list(coords[-2]), variables,
                     f"pin {component_name}.{name}.normal_points[0]"),
        _parse_point(list(coords[-1]), variables,
                     f"pin {component_name}.{name}.normal_points[1]"),
    ]
    _points_from_normal_points(component_name, name, normal_points, 1.0)
    return normal_points


def _points_from_normal_points(component_name: str, name: str,
                               normal_points: list[list[float]],
                               width: float) -> list[list[float]]:
    start = np.array(normal_points[0], dtype=float)
    end = np.array(normal_points[1], dtype=float)
    normal = end - start
    norm = np.linalg.norm(normal)
    if norm == 0:
        raise DesignDslError(
            f"Pin {component_name}.{name} normal_segment source has zero "
            "length")
    normal = normal / norm
    point_a = np.round(draw.Vector.rotate(normal, np.pi / 2)) * width / 2 + end
    point_b = np.round(draw.Vector.rotate(normal, -np.pi / 2)) * width / 2 + end
    return [point_a.tolist(), point_b.tolist()]


def _pin_from_spec(component_name: str, spec: Mapping[str, Any],
                   transform: Mapping[str, Any],
                   variables: Mapping[str, Any],
                   operations: Optional[Mapping[str, Any]] = None) -> PinIR:
    if not isinstance(spec, Mapping):
        raise DesignDslError(f"Pin in {component_name!r} must be a mapping")
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"Pin in {component_name!r} requires name")
    _reject_unknown_keys(spec, PIN_KEYS, f"pin {component_name}.{name}")
    width = _parse_number(spec.get("width"), variables,
                          f"pin {component_name}.{name}.width")
    mode = spec.get("mode", "tangent_points")
    input_as_norm = False
    normal_points = None
    if mode == "tangent_points":
        if "from_operation" in spec or "operation" in spec or "segment" in spec:
            raise DesignDslError(
                f"Pin {component_name}.{name} tangent_points does not accept "
                "from_operation, operation, or segment")
        if "points" not in spec:
            raise DesignDslError(
                f"Pin {component_name}.{name} tangent_points requires points")
        points = _parse_points(spec.get("points"), variables,
                               f"pin {component_name}.{name}.points")
        if len(points) != 2:
            raise DesignDslError(
                f"Pin {component_name}.{name} requires exactly two points")
        point_width = math.dist(points[0], points[1])
        if not math.isclose(point_width, width, rel_tol=1e-6, abs_tol=1e-9):
            raise DesignDslError(
                f"Pin {component_name}.{name} width {width} does not match "
                f"distance between points {point_width}")
    elif mode == "normal_segment":
        if "points" in spec:
            raise DesignDslError(
                f"Pin {component_name}.{name} normal_segment does not accept "
                "points")
        normal_points = _points_from_normal_segment(
            component_name, name, spec, variables, operations or {})
        points = normal_points
        input_as_norm = True
    else:
        raise DesignDslError(
            f"Pin {component_name}.{name} mode must be 'tangent_points' or "
            f"'normal_segment', got {mode!r}")
    merged_transform = _deep_merge(
        transform,
        _validate_transform(_optional_mapping(spec, "transform"),
                            f"{component_name}.{name}"),
    )
    points = _apply_transform_to_points(
        points, merged_transform, variables,
        f"pin {component_name}.{name}.transform")
    if normal_points is not None:
        normal_points = _apply_transform_to_points(normal_points,
                                                   merged_transform,
                                                   variables,
                                                   f"pin {component_name}."
                                                   f"{name}.transform")
        points = _points_from_normal_points(component_name, name,
                                            normal_points, width)

    return PinIR(component=component_name,
                 name=name,
                 points=points,
                 width=width,
                 gap=_parse_optional_number(spec.get("gap"), variables,
                                            f"pin {component_name}.{name}.gap")
                 if "gap" in spec else width * 0.6,
                 chip=str(spec.get("chip", "main")),
                 input_as_norm=input_as_norm,
                 normal_points=normal_points,
                 source=dict(spec))


def _generator_items(value: Any, owner: str) -> list[tuple[Any, Any]]:
    if isinstance(value, Mapping):
        return list(value.items())
    if isinstance(value, list):
        return list(enumerate(value))
    raise DesignDslError(f"{owner}.for_each must resolve to a mapping or list")


def _resolve_generator_iterator(value: Any,
                                ctx: Mapping[str, Any],
                                owner: str) -> Any:
    if isinstance(value, str) and "${" not in value:
        try:
            return _evaluate_expression(value, ctx)
        except DesignDslError as exc:
            raise DesignDslError(f"{owner}.for_each is invalid: {exc}") from exc
    return _walk_substitute(value, ctx)


def _expand_component_generators(
        component_name: str,
        generators: Mapping[str, Any],
        component_ctx: Mapping[str, Any],
        templates: Mapping[str, Any],
        variables: Mapping[str, Any],
        operation_outputs: Mapping[str, Any]) -> tuple[list[Any], list[Any],
                                                       dict[str, Any]]:
    if not isinstance(generators, Mapping):
        raise DesignDslError(f"component {component_name}.generators must be a mapping")

    generated_primitives: list[Any] = []
    generated_pins: list[Any] = []
    generated_operations: dict[str, Any] = {}
    for generator_name, generator_spec in generators.items():
        if not isinstance(generator_name, str) or not generator_name:
            raise DesignDslError(
                f"component {component_name}.generators keys must be strings")
        owner = f"component {component_name}.generators.{generator_name}"
        if not isinstance(generator_spec, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(generator_spec, GENERATOR_KEYS, owner)
        if generator_name in operation_outputs:
            raise DesignDslError(
                f"{owner} conflicts with component operation "
                f"{generator_name!r}")
        if generator_name in generated_operations:
            raise DesignDslError(
                f"Duplicate generator operation namespace: "
                f"{component_name}.{generator_name}")
        generated_operations[generator_name] = {}

        iterator_expr = generator_spec.get("for_each")
        if iterator_expr is None:
            raise DesignDslError(f"{owner}.for_each is required")
        iterator = _resolve_generator_iterator(iterator_expr, component_ctx,
                                               owner)
        local_name = generator_spec.get("as", "item")
        if not isinstance(local_name, str) or not local_name:
            raise DesignDslError(f"{owner}.as must be a non-empty string")

        operation_specs = _optional_mapping(generator_spec, "operations")
        primitive_specs = _optional_list(generator_spec, "primitives")
        pin_specs = _optional_list(generator_spec, "pins")
        for item_key, item_value in _generator_items(iterator, owner):
            item_key_text = str(item_key)
            if "." in item_key_text:
                raise DesignDslError(
                    f"{owner} item key {item_key_text!r} cannot contain '.'")
            if item_key_text in generated_operations[generator_name]:
                raise DesignDslError(
                    f"Duplicate generator item key: "
                    f"{component_name}.{generator_name}.{item_key_text}")
            local_ctx = {
                **component_ctx,
                local_name: {
                    "key": item_key,
                    "value": item_value,
                },
            }
            expanded_operations = _walk_substitute(operation_specs, local_ctx)
            operation_conflicts = (
                set(expanded_operations) & set(operation_outputs)
                if isinstance(expanded_operations, Mapping) else set())
            if operation_conflicts:
                raise DesignDslError(
                    f"{owner}.{item_key_text}.operations conflict with "
                    f"component operation(s): {sorted(operation_conflicts)}")
            iteration_owner = f"{owner}.{item_key}"
            iteration_outputs = evaluate_geometry_operations(
                expanded_operations,
                variables,
                initial_outputs=operation_outputs,
                owner=iteration_owner,
            )
            local_operation_outputs = {
                key: value
                for key, value in iteration_outputs.items()
                if key not in operation_outputs
            }
            generated_operations[generator_name][item_key_text] = (
                local_operation_outputs)

            namespace = f"{generator_name}.{item_key_text}"
            generated_primitives.extend(
                _namespace_generated_operation_refs(
                    spec,
                    local_operation_outputs,
                    namespace,
                )
                for spec in _expand_list(primitive_specs, local_ctx, templates)
            )
            generated_pins.extend(
                _namespace_generated_operation_refs(
                    spec,
                    local_operation_outputs,
                    namespace,
                )
                for spec in _expand_list(pin_specs, local_ctx, templates)
            )

    return generated_primitives, generated_pins, generated_operations


def _namespace_generated_operation_refs(spec: Any,
                                        local_operation_outputs: Mapping[str,
                                                                         Any],
                                        namespace: str) -> Any:
    if not isinstance(spec, Mapping):
        return spec
    out = dict(spec)
    for key in ("operation", "from_operation"):
        reference = out.get(key)
        if not isinstance(reference, str) or not reference:
            continue
        head = reference.split(".", 1)[0]
        if head in local_operation_outputs:
            out[key] = f"{namespace}.{reference}"
    return out


def _components_as_list(raw_components: Any) -> list[dict[str, Any]]:
    if isinstance(raw_components, Mapping):
        out = []
        for name, spec in raw_components.items():
            if not isinstance(spec, dict):
                raise DesignDslError(f"Component {name!r} must be a mapping")
            merged = dict(spec)
            if "name" in merged and merged["name"] != name:
                raise DesignDslError(
                    f"Component mapping key {name!r} does not match "
                    f"explicit name {merged['name']!r}")
            merged.setdefault("name", name)
            out.append(merged)
        return out
    if isinstance(raw_components, list):
        return raw_components
    raise DesignDslError("geometry.components must be a mapping or list")


def _split_endpoint(endpoint: str, where: str) -> dict[str, str]:
    if not isinstance(endpoint, str) or "." not in endpoint:
        raise DesignDslError(f"{where} must look like 'Component.pin'")
    component, pin = endpoint.split(".", 1)
    component = component.strip()
    pin = pin.strip()
    if not component or not pin:
        raise DesignDslError(f"{where} has an empty component or pin")
    return {"component": component, "pin": pin}


def _normalise_connections(netlist_spec: Any) -> list[dict[str, Any]]:
    if netlist_spec is None:
        return []
    if not isinstance(netlist_spec, Mapping):
        raise DesignDslError("netlist must be a mapping")
    _reject_unknown_keys(netlist_spec, NETLIST_KEYS, "netlist")
    connections = _optional_list(netlist_spec, "connections")
    if not isinstance(connections, list):
        raise DesignDslError("netlist.connections must be a list")
    out = []
    for index, connection in enumerate(connections):
        if not isinstance(connection, Mapping):
            raise DesignDslError(f"netlist.connections[{index}] must be a mapping")
        _reject_unknown_keys(connection, NETLIST_CONNECTION_KEYS,
                             f"netlist.connections[{index}]")
        from_pin = _split_endpoint(connection.get("from"),
                                   f"netlist.connections[{index}].from")
        to_pin = _split_endpoint(connection.get("to"),
                                 f"netlist.connections[{index}].to")
        out.append({"from": from_pin, "to": to_pin, "net_id": None})
    return out


def _bounds_list(bounds: tuple[float, float, float, float]) -> list[float]:
    return [float(value) for value in bounds]


def _derive(components: list[ComponentIR], netlist_spec: Any) -> dict[str, Any]:
    circuit_geometry: dict[str, Any] = {}
    for component in components:
        primitive_data: dict[str, Any] = {}
        pin_data: dict[str, Any] = {}
        bounds_geometries = []

        for primitive in component.primitives:
            item = {
                "kind": primitive.kind,
                "shape": primitive.shape,
                "bounds": _bounds_list(primitive.geometry.bounds),
            }
            if primitive.kind == "path":
                item["length"] = float(primitive.geometry.length)
            primitive_data[primitive.name] = item
            bounds_geometries.append(primitive.geometry)

        for pin in component.pins:
            points = [[float(x), float(y)] for x, y in pin.points]
            middle = [
                float((points[0][0] + points[1][0]) / 2.0),
                float((points[0][1] + points[1][1]) / 2.0),
            ]
            pin_data[pin.name] = {
                "points": points,
                "middle": middle,
                "width": float(pin.width),
                "gap": None if pin.gap is None else float(pin.gap),
                "chip": pin.chip,
            }

        if bounds_geometries:
            minx = min(geom.bounds[0] for geom in bounds_geometries)
            miny = min(geom.bounds[1] for geom in bounds_geometries)
            maxx = max(geom.bounds[2] for geom in bounds_geometries)
            maxy = max(geom.bounds[3] for geom in bounds_geometries)
            bounds = [float(minx), float(miny), float(maxx), float(maxy)]
        else:
            bounds = None

        circuit_geometry[component.name] = {
            "bounds": bounds,
            "primitives": primitive_data,
            "pins": pin_data,
        }

    return {
        "circuit": {
            "geometry": circuit_geometry,
        },
        "netlist": {
            "connections": _normalise_connections(netlist_spec),
        },
    }


def _parse_components(geometry_spec: Mapping[str, Any], ctx: Mapping[str, Any],
                      templates: Mapping[str, Any],
                      template_registry: ComponentTemplateRegistry,
                      variables: Mapping[str, Any]) -> list[ComponentIR]:
    if "routes" in geometry_spec:
        raise DesignDslError(
            "v3 native geometry does not accept routes; use path primitives")
    raw_components = geometry_spec.get("components")
    if raw_components is None:
        raise DesignDslError("geometry.components is required")
    transforms = geometry_spec.get("transforms", {})
    if not isinstance(transforms, Mapping):
        raise DesignDslError("geometry.transforms must be a mapping")

    component_specs = _expand_list(_components_as_list(raw_components), ctx, templates)
    components: list[ComponentIR] = []
    component_names: set[str] = set()
    for comp_spec in component_specs:
        if not isinstance(comp_spec, dict):
            raise DesignDslError("Expanded component spec must be a mapping")
        if "class" in comp_spec:
            raise DesignDslError(
                "v3 native components do not accept qlibrary class entries")
        name = comp_spec.get("name")
        if not isinstance(name, str) or not name:
            raise DesignDslError("Each component requires a name")
        if name in component_names:
            raise DesignDslError(f"Duplicate component name: {name}")
        component_names.add(name)
        _reject_unknown_keys(comp_spec, COMPONENT_KEYS, f"component {name}")

        template_expansion = expand_component_template(comp_spec,
                                                       template_registry)
        template_type = None
        template_options: dict[str, Any] = {}
        template_id = None
        inherited: list[str] = []
        if template_expansion is not None:
            template_type = template_expansion.template_type
            template_options = _walk_substitute(template_expansion.options, ctx)
            template_id = template_expansion.template
            inherited = template_expansion.inherited
            comp_spec = template_expansion.spec
            comp_spec["options"] = template_options

        component_ctx = {
            **ctx,
            "component": {
                "name": name,
                "type": template_type,
            },
            "options": template_options,
        }
        generator_specs = _optional_mapping(comp_spec, "generators")
        comp_spec_without_generators = dict(comp_spec)
        comp_spec_without_generators.pop("generators", None)
        comp_spec = _walk_substitute(comp_spec_without_generators,
                                     component_ctx)
        if generator_specs:
            comp_spec["generators"] = generator_specs
        transform = _transform_spec(comp_spec, geometry_spec, name)
        operation_outputs = evaluate_geometry_operations(
            _optional_mapping(comp_spec, "operations"),
            variables,
            owner=f"component {name}",
        )
        generated_primitive_specs, generated_pin_specs, generated_operations = (
            _expand_component_generators(
                name,
                _optional_mapping(comp_spec, "generators"),
                component_ctx,
                templates,
                variables,
                operation_outputs,
            ))
        operation_outputs = _deep_merge(operation_outputs, generated_operations)

        primitive_specs = _expand_list(_optional_list(comp_spec, "primitives"),
                                       component_ctx, templates)
        primitive_specs.extend(generated_primitive_specs)
        pin_specs = _expand_list(_optional_list(comp_spec, "pins"),
                                 component_ctx, templates)
        pin_specs.extend(generated_pin_specs)
        primitives = []
        primitive_names: set[str] = set()
        for primitive in primitive_specs:
            primitive_ir = _primitive_from_spec(name, primitive, transform,
                                               variables, operation_outputs)
            if primitive_ir.name in primitive_names:
                raise DesignDslError(
                    f"Duplicate primitive name: {name}.{primitive_ir.name}")
            primitive_names.add(primitive_ir.name)
            primitives.append(primitive_ir)

        pins = []
        pin_names: set[str] = set()
        for pin in pin_specs:
            pin_ir = _pin_from_spec(name, pin, transform, variables,
                                    operation_outputs)
            if pin_ir.name in pin_names:
                raise DesignDslError(f"Duplicate pin name: {name}.{pin_ir.name}")
            pin_names.add(pin_ir.name)
            pins.append(pin_ir)
        components.append(
            ComponentIR(name=name,
                        primitives=primitives,
                        pins=pins,
                        metadata=_optional_mapping(comp_spec, "metadata"),
                        type=template_type,
                        options=template_options,
                        template=template_id,
                        inherited=inherited,
                        source=dict(comp_spec)))

    unknown_transform_components = set(transforms) - component_names
    if unknown_transform_components:
        raise DesignDslError(
            "geometry.transforms references unknown component(s): "
            f"{sorted(unknown_transform_components)}")

    return components


def _validate_netlist_endpoints(components: list[ComponentIR],
                                connections: list[dict[str, Any]]) -> None:
    pin_names = {
        component.name: {pin.name for pin in component.pins}
        for component in components
    }
    used_endpoints: set[tuple[str, str]] = set()
    for connection in connections:
        endpoint_pairs = [
            (connection["from"]["component"], connection["from"]["pin"]),
            (connection["to"]["component"], connection["to"]["pin"]),
        ]
        if endpoint_pairs[0] == endpoint_pairs[1]:
            component, pin = endpoint_pairs[0]
            raise DesignDslError(
                f"netlist self-connection is invalid: {component}.{pin}")
        for endpoint_pair in endpoint_pairs:
            if endpoint_pair in used_endpoints:
                component, pin = endpoint_pair
                raise DesignDslError(
                    f"netlist endpoint reused: {component}.{pin}")
            used_endpoints.add(endpoint_pair)
        for endpoint in (connection["from"], connection["to"]):
            comp_name = endpoint["component"]
            pin_name = endpoint["pin"]
            if comp_name not in pin_names:
                raise DesignDslError(
                    f"netlist references unknown component {comp_name!r}")
            if pin_name not in pin_names[comp_name]:
                raise DesignDslError(
                    f"netlist references unknown pin {comp_name}.{pin_name}")


def _parse_chip_size(value: Any) -> tuple[Optional[str], Optional[str]]:
    if isinstance(value, str):
        parts = re.split(r"\s*[xX]\s*", value.strip())
        if len(parts) != 2:
            raise DesignDslError("chip.size must look like '10mm x 10mm'")
        return parts[0], parts[1]
    if isinstance(value, list):
        if len(value) != 2:
            raise DesignDslError("chip.size list must be [size_x, size_y]")
        return str(value[0]), str(value[1])
    if isinstance(value, dict):
        return value.get("size_x"), value.get("size_y")
    raise DesignDslError(f"Unsupported chip.size value: {value!r}")


def _validate_chip_spec(chip_spec: Mapping[str, Any]) -> None:
    _reject_unknown_keys(chip_spec, CHIP_KEYS, "geometry.design.chip")
    size = chip_spec.get("size")
    if isinstance(size, Mapping):
        _reject_unknown_keys(size, CHIP_SIZE_KEYS, "geometry.design.chip.size")


def _validate_design_spec(design_spec: Mapping[str, Any]) -> None:
    _reject_unknown_keys(design_spec, DESIGN_KEYS, "geometry.design")
    if "chip" in design_spec:
        _validate_chip_spec(_optional_mapping(design_spec, "chip"))


def _design_init_kwargs(design_spec: Mapping[str, Any]) -> dict[str, Any]:
    init_kwargs: dict[str, Any] = {}
    init_kwargs["enable_renderers"] = False
    if "metadata" in design_spec:
        init_kwargs["metadata"] = _optional_mapping(design_spec, "metadata")
    if "overwrite_enabled" in design_spec:
        init_kwargs["overwrite_enabled"] = _as_bool(
            design_spec["overwrite_enabled"], "geometry.design.overwrite_enabled")
    if "enable_renderers" in design_spec:
        init_kwargs["enable_renderers"] = _as_bool(
            design_spec["enable_renderers"], "geometry.design.enable_renderers")
    return init_kwargs


def _resolve_design_class(design_spec: Mapping[str, Any]):
    class_name = design_spec.get("class", "DesignPlanar")
    return _resolve_class(class_name, BUILTIN_DESIGNS, _USER_DESIGNS, "design")


def _design_variable_context(design_spec: Mapping[str, Any],
                             root_vars: Mapping[str, Any]) -> dict[str, Any]:
    """Return variables visible to DSL numeric parsing.

    Metal components can leave option defaults as symbolic names such as
    ``cpw_width``.  Resolve those names the same way qlibrary components do:
    start with the selected design's variables, then apply design-level and
    root DSL overrides.
    """
    _validate_design_spec(design_spec)
    design_cls = _resolve_design_class(design_spec)
    init_kwargs = _design_init_kwargs(design_spec)
    init_kwargs["enable_renderers"] = False  # variable-discovery only; don't spin up renderers
    design = design_cls(**init_kwargs)
    return {
        **dict(design.variables),
        **_optional_mapping(design_spec, "variables"),
        **dict(root_vars),
    }


def _instantiate_design(design_spec: Mapping[str, Any]):
    _validate_design_spec(design_spec)
    design_cls = _resolve_design_class(design_spec)
    design = design_cls(**_design_init_kwargs(design_spec))
    for key, value in _optional_mapping(design_spec, "variables").items():
        design.variables[key] = value

    chip_spec = _optional_mapping(design_spec, "chip")
    if chip_spec:
        _validate_chip_spec(chip_spec)
        chip_name = chip_spec.get("name", "main")
        if chip_name not in design.chips:
            raise DesignDslError(f"design has no chip {chip_name!r}")
        chip_size = design.chips[chip_name]["size"]
        if "size" in chip_spec:
            size_x, size_y = _parse_chip_size(chip_spec["size"])
            if size_x is not None:
                chip_size["size_x"] = size_x
            if size_y is not None:
                chip_size["size_y"] = size_y
        for key in ("size_x", "size_y", "size_z", "center_x", "center_y",
                    "center_z"):
            if key in chip_spec:
                chip_size[key] = chip_spec[key]
    return design


def build_ir(source: Union[str, Path],
             *,
             overrides: Optional[Mapping[str, Any]] = None) -> DesignIR:
    """Build a resolved native v3 IR from a YAML file or YAML text."""
    spec, base_dir = _load_yaml(source)
    spec = _expand_includes(spec, base_dir)
    if overrides:
        spec = _deep_merge(spec, dict(overrides))

    _reject_unknown_keys(spec, ROOT_KEYS, "root")

    schema = spec.get("schema")
    if schema != CURRENT_SCHEMA:
        raise DesignDslError(
            f"Unsupported schema {schema!r}; expected {CURRENT_SCHEMA!r}")

    geometry_spec = spec.get("geometry")
    if not isinstance(geometry_spec, Mapping):
        raise DesignDslError("geometry must be a mapping")
    _reject_unknown_keys(geometry_spec, GEOMETRY_KEYS, "geometry")
    design_spec = geometry_spec.get("design")
    if not isinstance(design_spec, Mapping):
        raise DesignDslError("geometry.design must be a mapping")
    _reject_unknown_keys(design_spec, DESIGN_KEYS, "geometry.design")

    vars_table = _optional_mapping(spec, "vars")
    ctx_vars = {**vars_table, "vars": vars_table}
    circuit = _walk_substitute(_optional_mapping(spec, "circuit"), ctx_vars)
    hamiltonian = _walk_substitute(
        _optional_mapping(spec, "hamiltonian"),
        {**ctx_vars, "circuit": circuit},
    )
    netlist_spec = None
    if "netlist" in spec:
        netlist_spec = spec["netlist"]
        if not isinstance(netlist_spec, Mapping):
            raise DesignDslError("netlist must be a mapping")
        _reject_unknown_keys(netlist_spec, NETLIST_KEYS, "netlist")
    netlist = _walk_substitute(
        dict(netlist_spec or {}),
        {**ctx_vars, "circuit": circuit, "hamiltonian": hamiltonian},
    )
    ctx = {
        **vars_table,
        "vars": vars_table,
        "circuit": circuit,
        "hamiltonian": hamiltonian,
        "netlist": netlist,
    }

    resolved_geometry = dict(geometry_spec)
    resolved_geometry["design"] = _walk_substitute(geometry_spec["design"], ctx)
    if "transforms" in geometry_spec:
        resolved_geometry["transforms"] = _walk_substitute(
            geometry_spec["transforms"], ctx)
    design_spec = dict(resolved_geometry["design"])
    _validate_design_spec(design_spec)
    variable_context = _design_variable_context(design_spec, vars_table)
    component_ctx = {
        **variable_context,
        "vars": variable_context,
        "circuit": circuit,
        "hamiltonian": hamiltonian,
        "netlist": netlist,
    }
    templates = _deep_merge(_optional_mapping(spec, "templates"),
                            _optional_mapping(resolved_geometry, "templates"))
    template_registry = ComponentTemplateRegistry(templates, base_dir=base_dir)
    components = _parse_components(resolved_geometry, component_ctx, templates,
                                   template_registry, variable_context)
    derived = _derive(components, netlist)
    _validate_netlist_endpoints(components, derived["netlist"]["connections"])

    metadata_geometry = {
        "design": design_spec,
        "templates": templates,
        "components": {
            component.name: component.source for component in components
        },
    }
    if "transforms" in resolved_geometry:
        metadata_geometry["transforms"] = resolved_geometry["transforms"]

    return DesignIR(schema=schema,
                    vars=vars_table,
                    hamiltonian=hamiltonian,
                    circuit=circuit,
                    netlist=netlist,
                    design=design_spec,
                    components=components,
                    geometry=metadata_geometry,
                    derived=derived)


def _component_pin_names(component: ComponentIR) -> set[str]:
    return {pin.name for pin in component.pins}


def _validate_component_chips(design, component_ir: ComponentIR) -> None:
    known_chips = set(design.chips.keys())
    for primitive in component_ir.primitives:
        if primitive.chip not in known_chips:
            raise DesignDslError(
                f"Primitive {component_ir.name}.{primitive.name} references "
                f"unknown chip {primitive.chip!r}")
    for pin in component_ir.pins:
        if pin.chip not in known_chips:
            raise DesignDslError(
                f"Pin {component_ir.name}.{pin.name} references unknown chip "
                f"{pin.chip!r}")


def export_ir_to_metal(
    ir: DesignIR,
    *,
    post_build: Optional[Callable[[Any], None]] = None,
):
    """Export a native IR into a regular Metal QDesign."""
    design = _instantiate_design(ir.design)
    component_objects: dict[str, NativeComponent] = {}
    component_irs = {component.name: component for component in ir.components}

    for component_ir in ir.components:
        _validate_component_chips(design, component_ir)
        component = NativeComponent(design, component_ir.name, make=False)
        component.metadata.update(component_ir.metadata)
        component_objects[component_ir.name] = component

        for primitive in component_ir.primitives:
            options = dict(primitive.options)
            if primitive.width is not None:
                options["width"] = primitive.width
            if primitive.fillet is not None:
                options["fillet"] = primitive.fillet
            if primitive.kind in component.qgeometry_table_usage:
                component.qgeometry_table_usage[primitive.kind] = True
            design.qgeometry.add_qgeometry(primitive.kind,
                                           component.id, {
                                               primitive.name:
                                                   primitive.geometry
                                           },
                                           subtract=primitive.subtract,
                                           helper=primitive.helper,
                                           layer=primitive.layer,
                                           chip=primitive.chip,
                                           **options)

        for pin in component_ir.pins:
            pin_points = pin.normal_points if pin.input_as_norm else pin.points
            component.add_pin(pin.name,
                              np.array(pin_points, dtype=float),
                              pin.width,
                              input_as_norm=pin.input_as_norm,
                              chip=pin.chip,
                              gap=pin.gap)

    for connection in ir.derived["netlist"]["connections"]:
        from_pin = connection["from"]
        to_pin = connection["to"]
        for endpoint in (from_pin, to_pin):
            comp_name = endpoint["component"]
            pin_name = endpoint["pin"]
            if comp_name not in component_objects:
                raise DesignDslError(
                    f"netlist references unknown component {comp_name!r}")
            if pin_name not in _component_pin_names(component_irs[comp_name]):
                raise DesignDslError(
                    f"netlist references unknown pin {comp_name}.{pin_name}")

        net_id = design.connect_pins(component_objects[from_pin["component"]].id,
                                     from_pin["pin"],
                                     component_objects[to_pin["component"]].id,
                                     to_pin["pin"])
        if not net_id:
            raise DesignDslError(
                f"Could not connect {from_pin} to {to_pin}; pin may be in use")
        connection["net_id"] = int(net_id)

    design.metadata["dsl_chain"] = ir.to_metadata()
    if post_build is not None:
        post_build(design)
    return design


def build_design(
    source: Union[str, Path],
    *,
    overrides: Optional[Mapping[str, Any]] = None,
    post_build: Optional[Callable[[Any], None]] = None,
):
    """Build a Metal QDesign by resolving v3 YAML into IR, then exporting it."""
    ir = build_ir(source, overrides=overrides)
    return export_ir_to_metal(ir, post_build=post_build)
