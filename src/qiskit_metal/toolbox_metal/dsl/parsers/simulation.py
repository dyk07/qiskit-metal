# -*- coding: utf-8 -*-
"""Simulation / Gmsh block parsers for DSL v3."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..errors import DesignDslError
from .._helpers import (
    parse_number as _parse_number,
    reject_unknown_keys as _reject_unknown_keys,
)
from ..expression import walk_substitute as _walk_substitute
from ..ir import ComponentIR
from ..schema import (
    AIRBOX_KEYS,
    GMSH_SIM_KEYS,
    LAYER_STACK_ENTRY_KEYS,
    LAYER_STACK_KINDS,
    MESH_KEYS,
    MESH_REFINE_KEYS,
    OUTPUT_KEYS,
    PORT_KEYS,
    PORT_TYPES,
    SIMULATION_KEYS,
    SYMMETRY_CONDITIONS,
    SYMMETRY_KEYS,
    SYMMETRY_PLANES,
)

__all__ = [
    "_parse_simulation",
    "_parse_gmsh_simulation",
    "_parse_layer_stack",
    "_parse_airbox",
    "_parse_ports",
    "_parse_symmetry",
    "_parse_mesh_settings",
    "_parse_output_settings",
    "_parse_scalar_with_optional_unit",
    "_SIMPLE_UNIT_SUFFIX_RE",
    "_ALLOWED_IMPEDANCE_UNITS",
]

_SIMPLE_UNIT_SUFFIX_RE = re.compile(
    r"^\s*([+\-]?\d*\.?\d+(?:[eE][+\-]?\d+)?)\s*([A-Za-z]+)?\s*$")
_ALLOWED_IMPEDANCE_UNITS = {"", "ohm", "ohms", "Ohm", "Ohms", "OHM", "OHMS"}


def _parse_scalar_with_optional_unit(value: Any, variables: Mapping[str, Any],
                                     *, owner: str,
                                     allowed_units: set[str]) -> float:
    """Parse a number with a permitted non-length unit suffix (e.g. ``"50ohm"``).

    Dedicated to impedance / eps_r / tan_delta / scaling / value fields that
    use non-length units.  Length fields should use ``_parse_number``
    (``parse_value``, default mm).  ``parse_value`` would raise a pint dimension
    error for ``"50ohm"`` and fall back to the raw string, so here we strip the
    allowed unit suffix manually before calling ``float()``.  ``allowed_units``
    containing ``""`` means bare numbers are accepted.
    Variable interpolation (``"${var}"``) is resolved upstream by
    ``_walk_substitute``.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        match = _SIMPLE_UNIT_SUFFIX_RE.match(stripped)
        if match is None:
            raise DesignDslError(
                f"{owner} must be a number with optional unit, got "
                f"{value!r}")
        number_part, unit_part = match.group(1), (match.group(2) or "")
        if unit_part not in allowed_units:
            raise DesignDslError(
                f"{owner} has unsupported unit {unit_part!r}; expected one "
                f"of {sorted(allowed_units)}")
        try:
            return float(number_part)
        except ValueError as exc:
            raise DesignDslError(
                f"{owner} numeric portion is invalid: {value!r}") from exc
    raise DesignDslError(
        f"{owner} must be a number or '<number><unit>', got {value!r}")


def _parse_simulation(spec: Any, ctx: Mapping[str, Any],
                      variables: Mapping[str, Any],
                      components: list[ComponentIR]) -> dict[str, Any]:
    """Resolve the optional ``simulation`` block into plain Python values.

    All length literals (``"12um"`` etc.) are parsed here into mm floats,
    consistent with ``PrimitiveIR.geometry`` / ``PinIR.width``; the adapter
    entry point multiplies by 1e-3 to convert to SI.  The returned dict
    contains only resolved values — no ``${...}`` strings remain.
    """
    if spec is None:
        return {}
    if not isinstance(spec, Mapping):
        raise DesignDslError("simulation must be a mapping")
    spec = _walk_substitute(dict(spec), ctx)
    _reject_unknown_keys(spec, SIMULATION_KEYS, "simulation")

    out: dict[str, Any] = {}
    if "gmsh" in spec:
        out["gmsh"] = _parse_gmsh_simulation(spec["gmsh"], variables, components)
    return out


def _parse_gmsh_simulation(node: Any, variables: Mapping[str, Any],
                            components: list[ComponentIR]) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh must be a mapping")
    _reject_unknown_keys(node, GMSH_SIM_KEYS, "simulation.gmsh")

    out: dict[str, Any] = {}
    if "layer_stack" in node:
        out["layer_stack"] = _parse_layer_stack(node["layer_stack"], variables)
    if "airbox" in node:
        out["airbox"] = _parse_airbox(node["airbox"], variables)
    if "ports" in node:
        out["ports"] = _parse_ports(node["ports"], variables, components)
    if "symmetry" in node:
        out["symmetry"] = _parse_symmetry(node["symmetry"])
    if "mesh" in node:
        out["mesh"] = _parse_mesh_settings(node["mesh"], variables)
    if "output" in node:
        out["output"] = _parse_output_settings(node["output"], variables)

    # plan §0 end-of-section requirement: when the gmsh block is present,
    # layer_stack is mandatory and must contain at least one metal entry.
    if "layer_stack" not in out:
        raise DesignDslError("simulation.gmsh.layer_stack is required")
    stack = out["layer_stack"]
    if not stack:
        raise DesignDslError(
            "simulation.gmsh.layer_stack must declare at least one layer")
    if not any(entry["kind"] == "metal" for entry in stack.values()):
        raise DesignDslError(
            "simulation.gmsh.layer_stack must contain at least one metal layer")

    # plan §10 risk register: stack must cover all primitive.layer values.
    declared_layers = set(stack.keys())
    referenced_layers = {
        primitive.layer
        for component in components
        for primitive in component.primitives
    }
    missing = referenced_layers - declared_layers
    if missing:
        raise DesignDslError(
            f"simulation.gmsh.layer_stack missing layer(s) referenced by "
            f"primitives: {sorted(missing)}")
    return out


def _parse_layer_stack(node: Any,
                       variables: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    if not isinstance(node, Mapping):
        raise DesignDslError(
            "simulation.gmsh.layer_stack must be a mapping {layer: spec}")
    out: dict[int, dict[str, Any]] = {}
    for raw_key, entry in node.items():
        try:
            layer = int(raw_key)
        except (TypeError, ValueError) as exc:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack key must be int, got "
                f"{raw_key!r}") from exc
        if not isinstance(entry, Mapping):
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}] must be a mapping")
        _reject_unknown_keys(
            entry, LAYER_STACK_ENTRY_KEYS,
            f"simulation.gmsh.layer_stack[{layer}]")
        kind = entry.get("kind")
        if kind not in LAYER_STACK_KINDS:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].kind must be one of "
                f"{sorted(LAYER_STACK_KINDS)}, got {kind!r}")
        if "thickness" not in entry:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].thickness is required")
        thickness = _parse_number(
            entry["thickness"], variables,
            owner=f"simulation.gmsh.layer_stack[{layer}].thickness")
        if thickness == 0:
            raise DesignDslError(
                f"simulation.gmsh.layer_stack[{layer}].thickness must be "
                f"non-zero (negative = dielectric extruded toward -z)")
        z = _parse_number(
            entry.get("z", 0.0), variables,
            owner=f"simulation.gmsh.layer_stack[{layer}].z")
        resolved: dict[str, Any] = {
            "kind": kind,
            "thickness": thickness,
            "z": z,
        }
        if "material" in entry:
            material = entry["material"]
            if not isinstance(material, str) or not material:
                raise DesignDslError(
                    f"simulation.gmsh.layer_stack[{layer}].material must be a "
                    f"non-empty string")
            resolved["material"] = material
        if "eps_r" in entry:
            resolved["eps_r"] = _parse_scalar_with_optional_unit(
                entry["eps_r"], variables,
                owner=f"simulation.gmsh.layer_stack[{layer}].eps_r",
                allowed_units={""})
        if "tan_delta" in entry:
            resolved["tan_delta"] = _parse_scalar_with_optional_unit(
                entry["tan_delta"], variables,
                owner=f"simulation.gmsh.layer_stack[{layer}].tan_delta",
                allowed_units={""})
        out[layer] = resolved
    return out


def _parse_airbox(node: Any,
                  variables: Mapping[str, Any]) -> dict[str, float]:
    """Parse the ``simulation.gmsh.airbox`` block.

    Bug #12 fix: ``top`` and ``bottom`` must be strictly positive (> 0) because
    ``render_vacuum_box`` requires them to extrude above and below the substrate.
    ``side_buffer`` must be non-negative (>= 0).
    """
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.airbox must be a mapping")
    _reject_unknown_keys(node, AIRBOX_KEYS, "simulation.gmsh.airbox")
    out: dict[str, float] = {}
    for key in AIRBOX_KEYS:
        if key in node:
            value = _parse_number(node[key], variables,
                                  owner=f"simulation.gmsh.airbox.{key}")
            if key in {"top", "bottom"}:
                if value <= 0:
                    raise DesignDslError(
                        f"simulation.gmsh.airbox.{key} must be > 0 "
                        f"(got {value}; render_vacuum_box requires strictly positive)")
            else:
                if value < 0:
                    raise DesignDslError(
                        f"simulation.gmsh.airbox.{key} must be >= 0, got {value}")
            out[key] = value
    return out


def _parse_ports(
    node: Any,
    variables: Mapping[str, Any],
    components: list[ComponentIR],
) -> list[dict[str, Any]]:
    if not isinstance(node, list):
        raise DesignDslError("simulation.gmsh.ports must be a list")
    component_pins: dict[str, set[str]] = {
        component.name: {pin.name for pin in component.pins}
        for component in components
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(node):
        owner = f"simulation.gmsh.ports[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, PORT_KEYS, owner)
        pin_ref = entry.get("pin")
        if not isinstance(pin_ref, str) or "." not in pin_ref:
            raise DesignDslError(
                f"{owner}.pin must be 'component.pin', got {pin_ref!r}")
        comp_name, pin_name = pin_ref.rsplit(".", 1)
        if comp_name not in component_pins:
            raise DesignDslError(
                f"{owner}.pin references unknown component {comp_name!r}")
        if pin_name not in component_pins[comp_name]:
            raise DesignDslError(
                f"{owner}.pin references unknown pin "
                f"{comp_name}.{pin_name}")
        key = (comp_name, pin_name)
        if key in seen:
            raise DesignDslError(
                f"{owner}.pin reuses endpoint {comp_name}.{pin_name}")
        seen.add(key)
        port_type = entry.get("type", "lumped")
        if port_type not in PORT_TYPES:
            raise DesignDslError(
                f"{owner}.type must be one of {sorted(PORT_TYPES)}, got "
                f"{port_type!r}")
        resolved: dict[str, Any] = {
            "component": comp_name,
            "pin": pin_name,
            "type": port_type,
        }
        if "impedance" in entry:
            resolved["impedance"] = _parse_scalar_with_optional_unit(
                entry["impedance"], variables,
                owner=f"{owner}.impedance",
                allowed_units=_ALLOWED_IMPEDANCE_UNITS)
        if "value" in entry:
            resolved["value"] = _parse_scalar_with_optional_unit(
                entry["value"], variables, owner=f"{owner}.value",
                allowed_units={""})
        out.append(resolved)
    return out


def _parse_symmetry(node: Any) -> list[dict[str, str]]:
    if not isinstance(node, list):
        raise DesignDslError("simulation.gmsh.symmetry must be a list")
    out: list[dict[str, str]] = []
    seen_planes: set[str] = set()
    for index, entry in enumerate(node):
        owner = f"simulation.gmsh.symmetry[{index}]"
        if not isinstance(entry, Mapping):
            raise DesignDslError(f"{owner} must be a mapping")
        _reject_unknown_keys(entry, SYMMETRY_KEYS, owner)
        plane = entry.get("plane")
        if plane not in SYMMETRY_PLANES:
            raise DesignDslError(
                f"{owner}.plane must be one of {sorted(SYMMETRY_PLANES)}, got "
                f"{plane!r}")
        if plane in seen_planes:
            raise DesignDslError(f"{owner}.plane {plane!r} declared twice")
        seen_planes.add(plane)
        condition = entry.get("condition", "pec")
        if condition not in SYMMETRY_CONDITIONS:
            raise DesignDslError(
                f"{owner}.condition must be one of "
                f"{sorted(SYMMETRY_CONDITIONS)}, got {condition!r}")
        out.append({"plane": plane, "condition": condition})
    return out


def _parse_mesh_settings(node: Any,
                         variables: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.mesh must be a mapping")
    _reject_unknown_keys(node, MESH_KEYS, "simulation.gmsh.mesh")
    out: dict[str, Any] = {}
    for key in ("max_size", "min_size", "max_size_jj"):
        if key in node:
            value = _parse_number(node[key], variables,
                                  owner=f"simulation.gmsh.mesh.{key}")
            if value <= 0:
                raise DesignDslError(
                    f"simulation.gmsh.mesh.{key} must be > 0, got {value}")
            out[key] = value
    if "conductor_refine" in node:
        refine = node["conductor_refine"]
        if not isinstance(refine, Mapping):
            raise DesignDslError(
                "simulation.gmsh.mesh.conductor_refine must be a mapping")
        _reject_unknown_keys(
            refine, MESH_REFINE_KEYS,
            "simulation.gmsh.mesh.conductor_refine")
        resolved_refine: dict[str, float] = {}
        for key in MESH_REFINE_KEYS:
            if key in refine:
                resolved_refine[key] = _parse_number(
                    refine[key], variables,
                    owner=f"simulation.gmsh.mesh.conductor_refine.{key}")
        out["conductor_refine"] = resolved_refine
    return out


def _parse_output_settings(node: Any,
                            variables: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(node, Mapping):
        raise DesignDslError("simulation.gmsh.output must be a mapping")
    _reject_unknown_keys(node, OUTPUT_KEYS, "simulation.gmsh.output")
    out: dict[str, Any] = {}
    if "format" in node:
        fmt = node["format"]
        if not isinstance(fmt, str) or not fmt:
            raise DesignDslError(
                "simulation.gmsh.output.format must be a non-empty string")
        out["format"] = fmt
    if "scaling" in node:
        out["scaling"] = _parse_scalar_with_optional_unit(
            node["scaling"], variables,
            owner="simulation.gmsh.output.scaling",
            allowed_units={""})
    return out
