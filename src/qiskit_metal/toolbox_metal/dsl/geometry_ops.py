# -*- coding: utf-8 -*-
"""Generic shapely geometry operations for YAML component templates."""

from __future__ import annotations

from collections.abc import Callable
from numbers import Number
from typing import Any, Mapping, Optional

import numpy as np
from shapely.geometry import CAP_STYLE, JOIN_STYLE, LineString, Polygon
from shapely.geometry.base import BaseGeometry

from qiskit_metal import draw
from qiskit_metal.toolbox_metal.parsing import parse_value

from .errors import DesignDslError

GeometryOperation = Callable[[Mapping[str, Any], Mapping[str, Any],
                              Mapping[str, Any], str], Any]


class GeometryOperationRegistry:
    """Registry for reusable, component-agnostic geometry operations."""

    def __init__(self):
        self._operations: dict[str, GeometryOperation] = {}

    def register(self, name: str, handler: GeometryOperation) -> None:
        """Register an operation handler by YAML ``op`` name."""
        if not isinstance(name, str) or not name:
            raise DesignDslError("geometry operation name must be non-empty")
        if not callable(handler):
            raise DesignDslError(f"geometry operation {name!r} is not callable")
        self._operations[name] = handler

    def evaluate(self, name: str, spec: Mapping[str, Any],
                 variables: Mapping[str, Any], outputs: Mapping[str, Any],
                 owner: str) -> Any:
        """Evaluate one operation spec."""
        try:
            handler = self._operations[name]
        except KeyError as exc:
            raise DesignDslError(
                f"Unknown geometry operation {name!r} for {owner}") from exc
        return handler(spec, variables, outputs, owner)

    @property
    def names(self) -> set[str]:
        """Return registered operation names."""
        return set(self._operations)


def evaluate_geometry_operations(
        operation_specs: Mapping[str, Any],
        variables: Mapping[str, Any],
        *,
        registry: Optional[GeometryOperationRegistry] = None,
        owner: str = "component") -> dict[str, Any]:
    """Evaluate ordered operation specs into local geometry outputs."""
    if not isinstance(operation_specs, Mapping):
        raise DesignDslError(f"{owner}.operations must be a mapping")

    registry = registry or DEFAULT_GEOMETRY_OPERATIONS
    outputs: dict[str, Any] = {}
    for operation_name, spec in operation_specs.items():
        if not isinstance(operation_name, str) or not operation_name:
            raise DesignDslError(f"{owner}.operations keys must be strings")
        if "." in operation_name:
            raise DesignDslError(
                f"{owner}.operations key {operation_name!r} cannot contain '.'")
        if not isinstance(spec, Mapping):
            raise DesignDslError(
                f"{owner}.operations.{operation_name} must be a mapping")
        op_name = spec.get("op")
        if not isinstance(op_name, str) or not op_name:
            raise DesignDslError(
                f"{owner}.operations.{operation_name}.op must be a "
                "non-empty string")
        outputs[operation_name] = registry.evaluate(
            op_name,
            spec,
            variables,
            outputs,
            f"{owner}.operations.{operation_name}",
        )
    return outputs


def resolve_operation_reference(outputs: Mapping[str, Any], reference: str,
                                owner: str) -> Any:
    """Resolve ``operation`` references such as ``wire`` or ``group.wire``."""
    if not isinstance(reference, str) or not reference:
        raise DesignDslError(f"{owner}.operation must be a non-empty string")

    current: Any = outputs
    for part in reference.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        if isinstance(current, (list, tuple)) and part.isdigit():
            index = int(part)
            try:
                current = current[index]
            except IndexError as exc:
                raise DesignDslError(
                    f"Unknown geometry operation reference {reference!r} "
                    f"for {owner}") from exc
            continue
        raise DesignDslError(
            f"Unknown geometry operation reference {reference!r} for {owner}")
    return current


def _reject_unknown_keys(spec: Mapping[str, Any], allowed: set[str],
                         owner: str) -> None:
    unknown = set(spec) - allowed
    if unknown:
        raise DesignDslError(
            f"Unknown geometry operation key(s) for {owner}: "
            f"{sorted(unknown)}")


def _parse_number(value: Any, variables: Mapping[str, Any], owner: str) -> float:
    parsed = parse_value(value, dict(variables))
    if isinstance(parsed, (int, float, np.number)) and not isinstance(
            parsed, bool):
        return float(parsed)
    raise DesignDslError(
        f"{owner} must be a numeric value with optional units, got {value!r}")


def _parse_optional_number(value: Any, variables: Mapping[str, Any],
                           owner: str) -> Optional[float]:
    if value is None:
        return None
    return _parse_number(value, variables, owner)


def _parse_point(value: Any, variables: Mapping[str, Any],
                 owner: str) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DesignDslError(f"{owner} must be [x, y], got {value!r}")
    return (
        _parse_number(value[0], variables, f"{owner}[0]"),
        _parse_number(value[1], variables, f"{owner}[1]"),
    )


def _parse_points(value: Any, variables: Mapping[str, Any],
                  owner: str) -> list[tuple[float, float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise DesignDslError(f"{owner} must be a list with at least two points")
    return [
        _parse_point(point, variables, f"{owner}[{index}]")
        for index, point in enumerate(value)
    ]


def _parse_angle(value: Any, owner: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, Number) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        raise DesignDslError(
            f"{owner} must be a number or '<number>deg', got {value!r}")
    stripped = value.strip()
    if stripped.endswith("deg"):
        stripped = stripped[:-3]
    try:
        return float(stripped)
    except ValueError as exc:
        raise DesignDslError(
            f"{owner} must be a number or '<number>deg', got {value!r}") from exc


def _parse_bool(value: Any, owner: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    if isinstance(value, (int, float, np.number)):
        if value == 1:
            return True
        if value == 0:
            return False
    raise DesignDslError(f"{owner} must be true or false, got {value!r}")


def _parse_origin(value: Any, variables: Mapping[str, Any],
                  owner: str) -> str | tuple[float, float]:
    if value is None:
        return "center"
    if isinstance(value, str):
        if value in {"center", "centroid"}:
            return value
        raise DesignDslError(
            f"{owner} must be 'center', 'centroid', or [x, y], got {value!r}")
    return _parse_point(value, variables, owner)


def _parse_style(value: Any, owner: str, choices: Mapping[str, Any]) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in choices:
            return choices[normalized]
        raise DesignDslError(
            f"{owner} must be one of {sorted(choices)}, got {value!r}")
    return value


def _source(spec: Mapping[str, Any], outputs: Mapping[str, Any],
            owner: str) -> Any:
    if "source" not in spec:
        raise DesignDslError(f"{owner}.source is required")
    source_ref = spec["source"]
    if isinstance(source_ref, str):
        return resolve_operation_reference(outputs, source_ref, owner)
    return source_ref


def _source_geometry(spec: Mapping[str, Any], outputs: Mapping[str, Any],
                     owner: str) -> BaseGeometry:
    geometry = _source(spec, outputs, owner)
    if not isinstance(geometry, BaseGeometry):
        raise DesignDslError(f"{owner}.source must resolve to a shapely geometry")
    return geometry


def _op_rectangle(spec: Mapping[str, Any], variables: Mapping[str, Any],
                  outputs: Mapping[str, Any], owner: str) -> Polygon:
    del outputs
    _reject_unknown_keys(spec, {"op", "width", "height", "xoff", "yoff"}, owner)
    width = _parse_number(spec.get("width"), variables, f"{owner}.width")
    height = _parse_number(spec.get("height"), variables, f"{owner}.height")
    xoff = _parse_number(spec.get("xoff", 0), variables, f"{owner}.xoff")
    yoff = _parse_number(spec.get("yoff", 0), variables, f"{owner}.yoff")
    return draw.rectangle(width, height, xoff=xoff, yoff=yoff)


def _op_polyline(spec: Mapping[str, Any], variables: Mapping[str, Any],
                 outputs: Mapping[str, Any], owner: str) -> LineString:
    del outputs
    _reject_unknown_keys(spec, {"op", "points"}, owner)
    return LineString(_parse_points(spec.get("points"), variables,
                                    f"{owner}.points"))


def _op_line(spec: Mapping[str, Any], variables: Mapping[str, Any],
             outputs: Mapping[str, Any], owner: str) -> LineString:
    line = _op_polyline(spec, variables, outputs, owner)
    if len(line.coords) != 2:
        raise DesignDslError(f"{owner}.points must contain exactly two points")
    return line


def _op_polygon(spec: Mapping[str, Any], variables: Mapping[str, Any],
                outputs: Mapping[str, Any], owner: str) -> Polygon:
    del outputs
    _reject_unknown_keys(spec, {"op", "points"}, owner)
    return Polygon(_parse_points(spec.get("points"), variables,
                                 f"{owner}.points"))


def _op_buffer(spec: Mapping[str, Any], variables: Mapping[str, Any],
               outputs: Mapping[str, Any], owner: str) -> BaseGeometry:
    _reject_unknown_keys(
        spec,
        {
            "op", "source", "distance", "resolution", "cap_style",
            "join_style", "mitre_limit",
        },
        owner,
    )
    geometry = _source_geometry(spec, outputs, owner)
    distance = _parse_number(spec.get("distance"), variables,
                             f"{owner}.distance")
    resolution = spec.get("resolution")
    if resolution is not None:
        resolution = int(_parse_number(resolution, variables,
                                       f"{owner}.resolution"))
    mitre_limit = _parse_optional_number(spec.get("mitre_limit"), variables,
                                         f"{owner}.mitre_limit")
    cap_style = _parse_style(
        spec.get("cap_style"),
        f"{owner}.cap_style",
        {
            "round": CAP_STYLE.round,
            "flat": CAP_STYLE.flat,
            "square": CAP_STYLE.square,
        },
    )
    join_style = _parse_style(
        spec.get("join_style"),
        f"{owner}.join_style",
        {
            "round": JOIN_STYLE.round,
            "mitre": JOIN_STYLE.mitre,
            "miter": JOIN_STYLE.mitre,
            "bevel": JOIN_STYLE.bevel,
        },
    )
    kwargs = {}
    if resolution is not None:
        kwargs["resolution"] = resolution
    if cap_style is not None:
        kwargs["cap_style"] = cap_style
    if join_style is not None:
        kwargs["join_style"] = join_style
    if mitre_limit is not None:
        kwargs["mitre_limit"] = mitre_limit
    return draw.buffer(geometry, distance, **kwargs)


def _op_translate(spec: Mapping[str, Any], variables: Mapping[str, Any],
                  outputs: Mapping[str, Any], owner: str) -> Any:
    _reject_unknown_keys(spec, {"op", "source", "xoff", "yoff", "zoff"}, owner)
    return draw.translate(
        _source(spec, outputs, owner),
        xoff=_parse_number(spec.get("xoff", 0), variables, f"{owner}.xoff"),
        yoff=_parse_number(spec.get("yoff", 0), variables, f"{owner}.yoff"),
        zoff=_parse_number(spec.get("zoff", 0), variables, f"{owner}.zoff"),
    )


def _op_scale(spec: Mapping[str, Any], variables: Mapping[str, Any],
              outputs: Mapping[str, Any], owner: str) -> Any:
    _reject_unknown_keys(
        spec,
        {"op", "source", "xfact", "yfact", "zfact", "origin"},
        owner,
    )
    return draw.scale(
        _source(spec, outputs, owner),
        xfact=_parse_number(spec.get("xfact", 1), variables,
                            f"{owner}.xfact"),
        yfact=_parse_number(spec.get("yfact", 1), variables,
                            f"{owner}.yfact"),
        zfact=_parse_number(spec.get("zfact", 1), variables,
                            f"{owner}.zfact"),
        origin=_parse_origin(spec.get("origin", "center"), variables,
                             f"{owner}.origin"),
    )


def _op_rotate(spec: Mapping[str, Any], variables: Mapping[str, Any],
               outputs: Mapping[str, Any], owner: str) -> Any:
    _reject_unknown_keys(
        spec,
        {"op", "source", "angle", "origin", "use_radians"},
        owner,
    )
    return draw.rotate(
        _source(spec, outputs, owner),
        _parse_angle(spec.get("angle", 0), f"{owner}.angle"),
        origin=_parse_origin(spec.get("origin", "center"), variables,
                             f"{owner}.origin"),
        use_radians=_parse_bool(spec.get("use_radians", False),
                                f"{owner}.use_radians"),
    )


def _op_rotate_position(spec: Mapping[str, Any], variables: Mapping[str, Any],
                        outputs: Mapping[str, Any], owner: str) -> Any:
    _reject_unknown_keys(
        spec,
        {"op", "source", "angle", "pos", "pos_rot"},
        owner,
    )
    pos_rot = _parse_point(spec.get("pos_rot", [0, 0]), variables,
                           f"{owner}.pos_rot")
    return draw.rotate_position(
        _source(spec, outputs, owner),
        _parse_angle(spec.get("angle", 0), f"{owner}.angle"),
        list(_parse_point(spec.get("pos", [0, 0]), variables, f"{owner}.pos")),
        pos_rot=pos_rot,
    )


def _op_last_segment(spec: Mapping[str, Any], variables: Mapping[str, Any],
                     outputs: Mapping[str, Any], owner: str) -> LineString:
    del variables
    _reject_unknown_keys(spec, {"op", "source"}, owner)
    geometry = _source_geometry(spec, outputs, owner)
    if not isinstance(geometry, LineString):
        raise DesignDslError(f"{owner}.source must resolve to a LineString")
    coords = list(geometry.coords)
    if len(coords) < 2:
        raise DesignDslError(f"{owner}.source must contain at least two points")
    return LineString(coords[-2:])


DEFAULT_GEOMETRY_OPERATIONS = GeometryOperationRegistry()
DEFAULT_GEOMETRY_OPERATIONS.register("rectangle", _op_rectangle)
DEFAULT_GEOMETRY_OPERATIONS.register("polyline", _op_polyline)
DEFAULT_GEOMETRY_OPERATIONS.register("line", _op_line)
DEFAULT_GEOMETRY_OPERATIONS.register("polygon", _op_polygon)
DEFAULT_GEOMETRY_OPERATIONS.register("buffer", _op_buffer)
DEFAULT_GEOMETRY_OPERATIONS.register("scale", _op_scale)
DEFAULT_GEOMETRY_OPERATIONS.register("translate", _op_translate)
DEFAULT_GEOMETRY_OPERATIONS.register("rotate", _op_rotate)
DEFAULT_GEOMETRY_OPERATIONS.register("rotate_position", _op_rotate_position)
DEFAULT_GEOMETRY_OPERATIONS.register("last_segment", _op_last_segment)


__all__ = [
    "DEFAULT_GEOMETRY_OPERATIONS",
    "GeometryOperationRegistry",
    "evaluate_geometry_operations",
    "resolve_operation_reference",
]
