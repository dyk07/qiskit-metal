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
from qiskit_metal.qlibrary.core.base import QComponent
from qiskit_metal.toolbox_metal.parsing import parse_value

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


BUILTIN_DESIGNS: dict[str, str] = {
    "DesignPlanar": "qiskit_metal.designs.design_planar.DesignPlanar",
    "DesignFlipChip": "qiskit_metal.designs.design_flipchip.DesignFlipChip",
    "DesignMultiPlanar":
        "qiskit_metal.designs.design_multiplanar.DesignMultiPlanar",
}

_USER_DESIGNS: dict[str, Any] = {}


class DesignDslError(Exception):
    """DSL parsing or export error."""


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
    source: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentIR:
    """A component container made only from primitives and pins."""

    name: str
    primitives: list[PrimitiveIR] = field(default_factory=list)
    pins: list[PinIR] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
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


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else value
        return out
    return override


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


_VAR_RE = re.compile(
    r"\$\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)\}")


def _resolve_path(ctx: Mapping[str, Any], path: str) -> Any:
    if path in ctx:
        return ctx[path]

    current: Any = ctx
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise DesignDslError(
                    f"Index out of range in ${{{path}}}: {index}") from exc
            continue
        raise DesignDslError(
            f"Unknown interpolation ${{{path}}}; available roots: {sorted(ctx)}")
    return current


def _substitute_string(value: str, ctx: Mapping[str, Any]) -> str:
    def _repl(match: re.Match) -> str:
        return str(_resolve_path(ctx, match.group(1)))

    return _VAR_RE.sub(_repl, value)


def _walk_substitute(node: Any, ctx: Mapping[str, Any]) -> Any:
    if isinstance(node, dict):
        return {key: _walk_substitute(val, ctx) for key, val in node.items()}
    if isinstance(node, list):
        return [_walk_substitute(item, ctx) for item in node]
    if isinstance(node, str):
        return _substitute_string(node, ctx)
    return node


def _load_yaml(source: Union[str, Path]) -> tuple[dict, Optional[Path]]:
    if isinstance(source, Path):
        return _load_yaml_file(source)

    if isinstance(source, str):
        candidate = Path(source)
        if "\n" not in source and len(source) < 4096 and candidate.exists():
            return _load_yaml_file(candidate)
        try:
            data = yaml.safe_load(source)
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
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise DesignDslError(f"YAML parse failed ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise DesignDslError(f"DSL document must be a mapping ({path})")
    return data, path.parent


def _expand_includes(node: Any, base_dir: Optional[Path]) -> Any:
    if isinstance(node, dict):
        if set(node.keys()) == {"$include"}:
            include_path = node["$include"]
            if not isinstance(include_path, str):
                raise DesignDslError("$include value must be a string path")
            if base_dir is None:
                raise DesignDslError(
                    "$include requires build_ir to receive a file path")
            included, child_dir = _load_yaml_file((base_dir / include_path).resolve())
            return _expand_includes(included, child_dir)
        return {key: _expand_includes(val, base_dir) for key, val in node.items()}
    if isinstance(node, list):
        return [_expand_includes(item, base_dir) for item in node]
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
        parent = _resolve_template(template["$extend"], templates, seen | {name})
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
    out: list[Any] = []
    for item in items:
        out.extend(_expand_node(item, ctx, templates))
    return out


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"true", "yes", "1"}
    return bool(value)


def _parse_number(value: Any, variables: Optional[Mapping[str, Any]] = None) -> float:
    parsed = parse_value(value, dict(variables or {}))
    if isinstance(parsed, (int, float, np.number)):
        return float(parsed)
    raise DesignDslError(f"Expected a numeric value with optional units, got {value!r}")


def _parse_optional_number(value: Any,
                           variables: Optional[Mapping[str, Any]] = None):
    if value is None:
        return None
    return _parse_number(value, variables)


def _parse_point(value: Any,
                 variables: Optional[Mapping[str, Any]] = None) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DesignDslError(f"Point must be [x, y], got {value!r}")
    return [_parse_number(value[0], variables), _parse_number(value[1], variables)]


def _parse_points(value: Any,
                  variables: Optional[Mapping[str, Any]] = None) -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise DesignDslError(f"points must be a list with at least two points")
    return [_parse_point(point, variables) for point in value]


def _parse_angle(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float, np.number)):
        return float(value)
    if not isinstance(value, str):
        raise DesignDslError(f"Angle must be a number or '<number>deg', got {value!r}")
    stripped = value.strip()
    if stripped.endswith("deg"):
        stripped = stripped[:-3]
    return float(stripped)


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


def _layer(value: Any) -> int:
    if value is None:
        return 1
    if isinstance(value, str):
        return int(float(value.strip()))
    return int(value)


def _transform_spec(component_spec: Mapping[str, Any],
                    geometry_spec: Mapping[str, Any],
                    component_name: str) -> dict[str, Any]:
    transforms = geometry_spec.get("transforms") or {}
    transform = {}
    if isinstance(transforms, Mapping):
        transform = dict(transforms.get(component_name) or {})
    transform = _deep_merge(transform, dict(component_spec.get("transform") or {}))
    for key in ("translate", "rotate", "origin"):
        if key in component_spec:
            transform[key] = component_spec[key]
    return transform


def _apply_transform_to_geometry(geometry: Any,
                                 transform: Mapping[str, Any],
                                 variables: Mapping[str, Any]) -> Any:
    origin = _parse_point(transform.get("origin", [0, 0]), variables)
    rotate = _parse_angle(transform.get("rotate", 0))
    translate = transform.get("translate", [0, 0])

    result = geometry
    if rotate:
        result = shapely.affinity.rotate(result, rotate, origin=tuple(origin))
    if translate:
        xoff, yoff = _parse_point(translate, variables)
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
                               variables: Mapping[str, Any]) -> list[list[float]]:
    origin = _parse_point(transform.get("origin", [0, 0]), variables)
    rotate = _parse_angle(transform.get("rotate", 0))
    translate = _parse_point(transform.get("translate", [0, 0]), variables)
    out = []
    for point in points:
        rotated = _rotate_point(point, rotate, origin)
        out.append([rotated[0] + translate[0], rotated[1] + translate[1]])
    return out


def _make_primitive_geometry(spec: Mapping[str, Any],
                             kind: str,
                             shape: str,
                             variables: Mapping[str, Any]) -> Any:
    if kind == "poly" and shape == "rectangle":
        center = _parse_point(spec.get("center", [0, 0]), variables)
        size = spec.get("size")
        if not isinstance(size, list) or len(size) != 2:
            raise DesignDslError("poly.rectangle requires size: [width, height]")
        width = _parse_number(size[0], variables)
        height = _parse_number(size[1], variables)
        x0, y0 = center[0] - width / 2.0, center[1] - height / 2.0
        x1, y1 = center[0] + width / 2.0, center[1] + height / 2.0
        return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])

    if kind == "poly" and shape == "polygon":
        return Polygon(_parse_points(spec.get("points"), variables))

    if kind == "path" and shape in {"line", "polyline"}:
        return LineString(_parse_points(spec.get("points"), variables))

    if kind == "junction" and shape == "line":
        points = _parse_points(spec.get("points"), variables)
        if len(points) != 2:
            raise DesignDslError("junction.line requires exactly two points")
        return LineString(points)

    raise DesignDslError(f"Unsupported primitive type: {kind}.{shape}")


def _primitive_from_spec(component_name: str, spec: Mapping[str, Any],
                         transform: Mapping[str, Any],
                         variables: Mapping[str, Any]) -> PrimitiveIR:
    if "class" in spec:
        raise DesignDslError(
            "v3 native geometry does not accept qlibrary class entries")
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"Primitive in {component_name!r} requires name")

    kind, shape = _parse_type(spec)
    geometry = _make_primitive_geometry(spec, kind, shape, variables)
    merged_transform = _deep_merge(transform, dict(spec.get("transform") or {}))
    geometry = _apply_transform_to_geometry(geometry, merged_transform, variables)

    reserved = {
        "name", "kind", "shape", "type", "primitive", "points", "center",
        "size", "subtract", "helper", "layer", "chip", "width", "fillet",
        "transform",
    }
    options = {key: val for key, val in spec.items() if key not in reserved}
    width = _parse_optional_number(spec.get("width"), variables)
    fillet = _parse_optional_number(spec.get("fillet"), variables)

    return PrimitiveIR(component=component_name,
                       name=name,
                       kind=kind,
                       shape=shape,
                       geometry=geometry,
                       subtract=_as_bool(spec.get("subtract", False)),
                       helper=_as_bool(spec.get("helper", False)),
                       layer=_layer(spec.get("layer")),
                       chip=str(spec.get("chip", "main")),
                       width=width,
                       fillet=fillet,
                       options=options,
                       source=dict(spec))


def _pin_from_spec(component_name: str, spec: Mapping[str, Any],
                   transform: Mapping[str, Any],
                   variables: Mapping[str, Any]) -> PinIR:
    name = spec.get("name")
    if not isinstance(name, str) or not name:
        raise DesignDslError(f"Pin in {component_name!r} requires name")
    points = _parse_points(spec.get("points"), variables)
    merged_transform = _deep_merge(transform, dict(spec.get("transform") or {}))
    points = _apply_transform_to_points(points, merged_transform, variables)

    return PinIR(component=component_name,
                 name=name,
                 points=points,
                 width=_parse_number(spec.get("width"), variables),
                 gap=_parse_optional_number(spec.get("gap"), variables),
                 chip=str(spec.get("chip", "main")),
                 source=dict(spec))


def _components_as_list(raw_components: Any) -> list[dict[str, Any]]:
    if isinstance(raw_components, Mapping):
        out = []
        for name, spec in raw_components.items():
            if not isinstance(spec, dict):
                raise DesignDslError(f"Component {name!r} must be a mapping")
            merged = dict(spec)
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
    if not isinstance(netlist_spec, Mapping):
        return []
    connections = netlist_spec.get("connections") or []
    if not isinstance(connections, list):
        raise DesignDslError("netlist.connections must be a list")
    out = []
    for index, connection in enumerate(connections):
        if not isinstance(connection, Mapping):
            raise DesignDslError(f"netlist.connections[{index}] must be a mapping")
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
                      variables: Mapping[str, Any]) -> list[ComponentIR]:
    if "routes" in geometry_spec:
        raise DesignDslError(
            "v3 native geometry does not accept routes; use path primitives")
    raw_components = geometry_spec.get("components")
    if raw_components is None:
        raise DesignDslError("geometry.components is required")

    component_specs = _expand_list(_components_as_list(raw_components), ctx, templates)
    components: list[ComponentIR] = []
    for comp_spec in component_specs:
        if not isinstance(comp_spec, dict):
            raise DesignDslError("Expanded component spec must be a mapping")
        if "class" in comp_spec:
            raise DesignDslError(
                "v3 native components do not accept qlibrary class entries")
        name = comp_spec.get("name")
        if not isinstance(name, str) or not name:
            raise DesignDslError("Each component requires a name")
        transform = _transform_spec(comp_spec, geometry_spec, name)

        primitive_specs = _expand_list(comp_spec.get("primitives") or [], ctx,
                                       templates)
        pin_specs = _expand_list(comp_spec.get("pins") or [], ctx, templates)
        primitives = [
            _primitive_from_spec(name, primitive, transform, variables)
            for primitive in primitive_specs
        ]
        pins = [
            _pin_from_spec(name, pin, transform, variables)
            for pin in pin_specs
        ]
        components.append(
            ComponentIR(name=name,
                        primitives=primitives,
                        pins=pins,
                        metadata=dict(comp_spec.get("metadata") or {}),
                        source=dict(comp_spec)))

    return components


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


def _instantiate_design(design_spec: Mapping[str, Any]):
    class_name = design_spec.get("class", "DesignPlanar")
    design_cls = _resolve_class(class_name, BUILTIN_DESIGNS, _USER_DESIGNS,
                                "design")
    init_kwargs: dict[str, Any] = {}
    if "metadata" in design_spec:
        init_kwargs["metadata"] = design_spec["metadata"]
    if "overwrite_enabled" in design_spec:
        init_kwargs["overwrite_enabled"] = _as_bool(
            design_spec["overwrite_enabled"])
    if "enable_renderers" in design_spec:
        init_kwargs["enable_renderers"] = _as_bool(
            design_spec["enable_renderers"])

    design = design_cls(**init_kwargs)
    for key, value in (design_spec.get("variables") or {}).items():
        design.variables[key] = value

    chip_spec = design_spec.get("chip")
    if chip_spec:
        chip_name = chip_spec.get("name", "main") if isinstance(chip_spec,
                                                                 dict) else "main"
        if chip_name not in design._chips:
            raise DesignDslError(f"design has no chip {chip_name!r}")
        chip_size = design._chips[chip_name]["size"]
        if isinstance(chip_spec, dict) and "size" in chip_spec:
            size_x, size_y = _parse_chip_size(chip_spec["size"])
            if size_x is not None:
                chip_size["size_x"] = size_x
            if size_y is not None:
                chip_size["size_y"] = size_y
        if isinstance(chip_spec, dict):
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

    schema = spec.get("schema")
    if schema != CURRENT_SCHEMA:
        raise DesignDslError(
            f"Unsupported schema {schema!r}; expected {CURRENT_SCHEMA!r}")

    geometry_spec = spec.get("geometry")
    if not isinstance(geometry_spec, Mapping):
        raise DesignDslError("geometry must be a mapping")
    design_spec = geometry_spec.get("design")
    if not isinstance(design_spec, Mapping):
        raise DesignDslError("geometry.design must be a mapping")

    vars_table = dict(spec.get("vars") or {})
    ctx_vars = {**vars_table, "vars": vars_table}
    circuit = _walk_substitute(spec.get("circuit") or {}, ctx_vars)
    hamiltonian = _walk_substitute(
        spec.get("hamiltonian") or {},
        {**ctx_vars, "circuit": circuit},
    )
    netlist = _walk_substitute(
        spec.get("netlist") or {},
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
    templates = _deep_merge(dict(spec.get("templates") or {}),
                            dict(resolved_geometry.get("templates") or {}))
    components = _parse_components(resolved_geometry, ctx, templates, vars_table)
    derived = _derive(components, netlist)

    metadata_geometry = {
        "design": design_spec,
        "templates": templates,
        "components": {
            component.name: component.source for component in components
        },
    }

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
        component = NativeComponent(design, component_ir.name, make=False)
        component.metadata.update(component_ir.metadata)
        component_objects[component_ir.name] = component

        for primitive in component_ir.primitives:
            options = dict(primitive.options)
            if primitive.width is not None:
                options["width"] = primitive.width
            if primitive.fillet is not None:
                options["fillet"] = primitive.fillet
            component.add_qgeometry(primitive.kind, {
                primitive.name: primitive.geometry
            },
                                    subtract=primitive.subtract,
                                    helper=primitive.helper,
                                    layer=primitive.layer,
                                    chip=primitive.chip,
                                    **options)

        for pin in component_ir.pins:
            component.add_pin(pin.name,
                              np.array(pin.points, dtype=float),
                              pin.width,
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
