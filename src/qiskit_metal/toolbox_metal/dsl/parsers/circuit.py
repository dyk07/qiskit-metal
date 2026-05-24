# -*- coding: utf-8 -*-
"""Circuit and netlist parsers for DSL v3."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import DesignDslError
from .._helpers import reject_unknown_keys as _reject_unknown_keys
from ..ir import ComponentIR
from ..schema import NETLIST_CONNECTION_KEYS, NETLIST_KEYS

__all__ = [
    "_split_endpoint",
    "_normalise_connections",
    "_bounds_list",
    "_derive",
    "_validate_netlist_endpoints",
]


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
    connections = netlist_spec.get("connections", [])
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
            item: dict[str, Any] = {
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
            bounds: Any = [float(minx), float(miny), float(maxx), float(maxy)]
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
