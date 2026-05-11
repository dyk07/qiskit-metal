# -*- coding: utf-8 -*-
"""Data model for reusable YAML component templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .errors import DesignDslError


TEMPLATE_SCHEMA = "qiskit-metal/component-template/1"

TEMPLATE_KEYS = {
    "schema",
    "id",
    "extends",
    "options",
    "metadata",
    "merge_rules",
    "geometry",
}
TEMPLATE_GEOMETRY_KEYS = {
    "primitives",
    "pins",
    "transform",
    "operations",
    "generators",
}


@dataclass(frozen=True)
class ComponentTemplate:
    """A normalized YAML component template."""

    id: str
    extends: Optional[str] = None
    options: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    geometry: dict[str, Any] = field(default_factory=dict)
    merge_rules: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)


def _reject_unknown_keys(spec: Mapping[str, Any], allowed: set[str],
                         owner: str) -> None:
    unknown = set(spec) - allowed
    if unknown:
        raise DesignDslError(f"Unknown {owner} key(s): {sorted(unknown)}")


def _mapping(value: Any, owner: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DesignDslError(f"{owner} must be a mapping")
    return dict(value)


def _optional_list(value: Any, owner: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DesignDslError(f"{owner} must be a list")
    return value


def component_template_from_mapping(spec: Mapping[str, Any],
                                    owner: str) -> ComponentTemplate:
    """Validate and normalize a component template mapping."""
    if not isinstance(spec, Mapping):
        raise DesignDslError(f"{owner} must be a mapping")
    _reject_unknown_keys(spec, TEMPLATE_KEYS, owner)

    schema = spec.get("schema")
    if schema != TEMPLATE_SCHEMA:
        raise DesignDslError(
            f"{owner}.schema must be {TEMPLATE_SCHEMA!r}, got {schema!r}")

    template_id = spec.get("id")
    if not isinstance(template_id, str) or not template_id:
        raise DesignDslError(f"{owner}.id must be a non-empty string")

    extends = spec.get("extends")
    if extends is not None and (not isinstance(extends, str) or not extends):
        raise DesignDslError(f"{owner}.extends must be null or a template id")

    geometry = _mapping(spec.get("geometry"), f"{owner}.geometry")
    _reject_unknown_keys(geometry, TEMPLATE_GEOMETRY_KEYS, f"{owner}.geometry")

    if "primitives" in geometry:
        geometry["primitives"] = _optional_list(
            geometry["primitives"], f"{owner}.geometry.primitives")
    if "pins" in geometry:
        geometry["pins"] = _optional_list(geometry["pins"],
                                          f"{owner}.geometry.pins")
    if "operations" in geometry:
        geometry["operations"] = _mapping(geometry["operations"],
                                          f"{owner}.geometry.operations")
    if "transform" in geometry:
        geometry["transform"] = _mapping(geometry["transform"],
                                         f"{owner}.geometry.transform")
    if "generators" in geometry:
        geometry["generators"] = _mapping(geometry["generators"],
                                          f"{owner}.geometry.generators")

    return ComponentTemplate(
        id=template_id,
        extends=extends,
        options=_mapping(spec.get("options"), f"{owner}.options"),
        metadata=_mapping(spec.get("metadata"), f"{owner}.metadata"),
        geometry=geometry,
        merge_rules=_mapping(spec.get("merge_rules"), f"{owner}.merge_rules"),
        source=dict(spec),
    )
