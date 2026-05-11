# -*- coding: utf-8 -*-
"""Generic shapely geometry operations for YAML component templates."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Mapping, Optional

from shapely.geometry import CAP_STYLE, JOIN_STYLE, LineString, Polygon
from shapely.geometry.base import BaseGeometry

from qiskit_metal import draw

from ._helpers import (
    parse_angle as _parse_angle,
    parse_bool as _parse_bool,
    parse_number as _parse_number,
    parse_optional_number as _parse_optional_number,
    parse_point as _parse_point,
    parse_points as _parse_points,
    reject_unknown_keys as _reject_unknown_keys,
)
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
        initial_outputs: Optional[Mapping[str, Any]] = None,
        owner: str = "component") -> dict[str, Any]:
    """Evaluate ordered operation specs into local geometry outputs."""
    if not isinstance(operation_specs, Mapping):
        raise DesignDslError(f"{owner}.operations must be a mapping")

    registry = registry or DEFAULT_GEOMETRY_OPERATIONS
    outputs: dict[str, Any] = dict(initial_outputs or {})
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


def _parse_origin(value: Any, variables: Mapping[str, Any],
                  owner: str) -> str | tuple[float, float]:
    if value is None:
        return "center"
    if isinstance(value, str):
        if value in {"center", "centroid"}:
            return value
        raise DesignDslError(
            f"{owner} must be 'center', 'centroid', or [x, y], got {value!r}")
    # shapely.affinity rejects list origins on 3D geometry (list + tuple TypeError)
    return tuple(_parse_point(value, variables, owner))


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
    # pos_rot becomes a shapely.affinity origin → must be a tuple, not a list
    pos_rot = tuple(_parse_point(spec.get("pos_rot", [0, 0]), variables,
                                 f"{owner}.pos_rot"))
    return draw.rotate_position(
        _source(spec, outputs, owner),
        _parse_angle(spec.get("angle", 0), f"{owner}.angle"),
        _parse_point(spec.get("pos", [0, 0]), variables, f"{owner}.pos"),
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


def _op_transform_group(spec: Mapping[str, Any], variables: Mapping[str, Any],
                        outputs: Mapping[str, Any], owner: str) -> dict[str, Any]:
    _reject_unknown_keys(spec, {"op", "sources", "steps"}, owner)
    sources = spec.get("sources")
    if isinstance(sources, Mapping):
        source_items = list(sources.items())
    elif isinstance(sources, list):
        source_items = []
        for index, source_ref in enumerate(sources):
            if not isinstance(source_ref, str) or not source_ref:
                raise DesignDslError(
                    f"{owner}.sources[{index}] must be an operation reference")
            source_items.append((source_ref.rsplit(".", 1)[-1], source_ref))
    else:
        raise DesignDslError(f"{owner}.sources must be a mapping or list")

    steps = spec.get("steps")
    if not isinstance(steps, list) or not steps:
        raise DesignDslError(f"{owner}.steps must be a non-empty list")

    transformed: dict[str, Any] = {}
    for source_name, source_ref in source_items:
        if not isinstance(source_name, str) or not source_name:
            raise DesignDslError(f"{owner}.sources keys must be strings")
        if source_name in transformed:
            raise DesignDslError(
                f"{owner}.sources has duplicate output key {source_name!r}")
        current = (resolve_operation_reference(outputs, source_ref, owner)
                   if isinstance(source_ref, str) else source_ref)
        for index, step in enumerate(steps):
            if not isinstance(step, Mapping):
                raise DesignDslError(
                    f"{owner}.steps[{index}] must be a mapping")
            if "source" in step:
                raise DesignDslError(
                    f"{owner}.steps[{index}] must not define source")
            op_name = step.get("op")
            if not isinstance(op_name, str) or not op_name:
                raise DesignDslError(
                    f"{owner}.steps[{index}].op must be a non-empty string")
            try:
                handler = _TRANSFORM_GROUP_STEP_OPERATIONS[op_name]
            except KeyError as exc:
                raise DesignDslError(
                    f"Unknown geometry operation {op_name!r} for "
                    f"{owner}.steps[{index}]") from exc
            current = handler(
                {
                    **dict(step),
                    "source": current,
                },
                variables,
                outputs,
                f"{owner}.steps[{index}]",
            )
        transformed[source_name] = current
    return transformed


_TRANSFORM_GROUP_STEP_OPERATIONS = {
    "scale": _op_scale,
    "translate": _op_translate,
    "rotate": _op_rotate,
    "rotate_position": _op_rotate_position,
}


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
DEFAULT_GEOMETRY_OPERATIONS.register("transform_group", _op_transform_group)


__all__ = [
    "DEFAULT_GEOMETRY_OPERATIONS",
    "GeometryOperationRegistry",
    "evaluate_geometry_operations",
    "resolve_operation_reference",
]
