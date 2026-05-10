# -*- coding: utf-8 -*-
"""Expansion of ``type``/``options`` component templates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from .errors import DesignDslError
from .template_registry import ComponentTemplateRegistry


@dataclass(frozen=True)
class ComponentTemplateExpansion:
    """A component spec after template defaults have been applied."""

    spec: dict[str, Any]
    template_type: str
    options: dict[str, Any]
    template: str
    inherited: list[str] = field(default_factory=list)


def expand_component_template(
        component_spec: Mapping[str, Any],
        registry: ComponentTemplateRegistry) -> ComponentTemplateExpansion | None:
    """Expand a typed component spec, or return ``None`` for primitive specs."""
    template_type = component_spec.get("type")
    if template_type is None:
        return None
    if not isinstance(template_type, str) or not template_type:
        raise DesignDslError("component type must be a non-empty string")

    instance_options = component_spec.get("options", {})
    if not isinstance(instance_options, Mapping):
        raise DesignDslError(
            f"component {component_spec.get('name', '<unnamed>')}.options "
            "must be a mapping")

    chain = registry.inheritance_chain(template_type)
    default_options: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    geometry: dict[str, Any] = {}
    merge_rules: dict[str, Any] = {}
    for template in chain:
        default_options = _deep_merge(default_options, template.options)
        metadata = _deep_merge(metadata, template.metadata)
        geometry = _merge_geometry(geometry, template.geometry)
        merge_rules = _deep_merge(merge_rules, template.merge_rules)

    _validate_option_overrides(default_options, instance_options,
                               f"component {component_spec.get('name')}.options")
    options = _deep_merge(default_options, dict(instance_options))

    instance_metadata = component_spec.get("metadata", {})
    if instance_metadata and not isinstance(instance_metadata, Mapping):
        raise DesignDslError(
            f"component {component_spec.get('name')}.metadata must be a mapping")
    metadata = _deep_merge(metadata, dict(instance_metadata or {}))
    metadata.setdefault("template", {})
    if isinstance(metadata["template"], Mapping):
        metadata["template"] = {
            **dict(metadata["template"]),
            "type": template_type,
            "inherited": [template.id for template in chain],
        }

    expanded = dict(component_spec)
    expanded["metadata"] = metadata
    expanded["options"] = options
    expanded["template"] = chain[-1].id
    expanded["inherited"] = [template.id for template in chain]

    template_primitives = list(geometry.get("primitives", []))
    template_pins = list(geometry.get("pins", []))
    instance_primitives = list(component_spec.get("primitives", []) or [])
    instance_pins = list(component_spec.get("pins", []) or [])
    expanded["primitives"] = template_primitives + instance_primitives
    expanded["pins"] = template_pins + instance_pins

    if "transform" in geometry:
        expanded["transform"] = _deep_merge(geometry["transform"],
                                            component_spec.get("transform", {}))

    return ComponentTemplateExpansion(
        spec=expanded,
        template_type=template_type,
        options=options,
        template=chain[-1].id,
        inherited=[template.id for template in chain],
    )


def _deep_merge(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = _deep_merge(out.get(key), value) if key in out else value
        return out
    return override


def _merge_geometry(base: Mapping[str, Any],
                    override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in {"primitives", "pins"}:
            out[key] = [*out.get(key, []), *list(value or [])]
        elif key == "transform":
            out[key] = _deep_merge(out.get(key, {}), value)
        else:
            out[key] = _deep_merge(out.get(key), value) if key in out else value
    return out


def _validate_option_overrides(defaults: Mapping[str, Any],
                               overrides: Mapping[str, Any],
                               owner: str) -> None:
    for key, value in overrides.items():
        if key not in defaults:
            raise DesignDslError(f"Unknown {owner} key(s): {[key]}")
        default_value = defaults[key]
        if isinstance(default_value, Mapping) and isinstance(value, Mapping):
            _validate_option_overrides(default_value, value, f"{owner}.{key}")
