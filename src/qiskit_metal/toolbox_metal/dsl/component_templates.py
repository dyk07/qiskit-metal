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

    options = _merge_options(default_options, dict(instance_options),
                             merge_rules,
                             f"component {component_spec.get('name')}.options")

    instance_metadata = component_spec.get("metadata", {})
    if "metadata" in component_spec and not isinstance(instance_metadata,
                                                       Mapping):
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

    template_operations = _optional_mapping_value(
        geometry.get("operations", {}),
        f"component template {template_type!r}.geometry.operations",
    )
    instance_operations = _optional_mapping_value(
        component_spec.get("operations", {}),
        f"component {component_spec.get('name')}.operations",
    )
    expanded["operations"] = _deep_merge(template_operations,
                                         instance_operations)
    template_generators = _optional_mapping_value(
        geometry.get("generators", {}),
        f"component template {template_type!r}.geometry.generators",
    )
    instance_generators = _optional_mapping_value(
        component_spec.get("generators", {}),
        f"component {component_spec.get('name')}.generators",
    )
    expanded["generators"] = _deep_merge(template_generators,
                                         instance_generators)

    template_primitives = _optional_list_value(
        geometry.get("primitives", []),
        f"component template {template_type!r}.geometry.primitives",
    )
    template_pins = _optional_list_value(
        geometry.get("pins", []),
        f"component template {template_type!r}.geometry.pins",
    )
    instance_primitives = _optional_list_value(
        component_spec.get("primitives", []),
        f"component {component_spec.get('name')}.primitives",
    )
    instance_pins = _optional_list_value(
        component_spec.get("pins", []),
        f"component {component_spec.get('name')}.pins",
    )
    expanded["primitives"] = template_primitives + instance_primitives
    expanded["pins"] = template_pins + instance_pins

    if "transform" in geometry:
        template_transform = _optional_mapping_value(
            geometry["transform"],
            f"component template {template_type!r}.geometry.transform",
        )
        instance_transform = _optional_mapping_value(
            component_spec.get("transform", {}),
            f"component {component_spec.get('name')}.transform",
        )
        expanded["transform"] = _deep_merge(template_transform,
                                            instance_transform)

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


def _optional_mapping_value(value: Any, owner: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DesignDslError(f"{owner} must be a mapping")
    return dict(value)


def _optional_list_value(value: Any, owner: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise DesignDslError(f"{owner} must be a list")
    return list(value)


def _merge_geometry(base: Mapping[str, Any],
                    override: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if key in {"primitives", "pins"}:
            out[key] = [*out.get(key, []), *list(value or [])]
        elif key == "operations":
            out[key] = _deep_merge(out.get(key, {}), value or {})
        elif key == "transform":
            out[key] = _deep_merge(out.get(key, {}), value)
        else:
            out[key] = _deep_merge(out.get(key), value) if key in out else value
    return out


def _merge_options(defaults: Mapping[str, Any], overrides: Mapping[str, Any],
                   merge_rules: Mapping[str, Any], owner: str) -> dict[str, Any]:
    _validate_option_overrides(defaults, overrides, owner, merge_rules)
    options = _deep_merge(dict(defaults), dict(overrides))
    _apply_merge_rules(options, merge_rules, owner)
    return options


def _validate_option_overrides(defaults: Mapping[str, Any],
                               overrides: Mapping[str, Any],
                               owner: str,
                               merge_rules: Mapping[str, Any]) -> None:
    for key, value in overrides.items():
        if key not in defaults:
            raise DesignDslError(f"Unknown {owner} key(s): {[key]}")
        default_value = defaults[key]
        rule = merge_rules.get(key)
        if _is_each_entry_extends_rule(rule):
            _validate_each_entry_override(defaults, key, value, rule, owner)
            continue
        if isinstance(default_value, Mapping) and isinstance(value, Mapping):
            nested_rules = rule if isinstance(rule, Mapping) else {}
            _validate_option_overrides(default_value, value, f"{owner}.{key}",
                                       nested_rules)


def _is_each_entry_extends_rule(rule: Any) -> bool:
    return isinstance(rule, Mapping) and "each_entry_extends" in rule


def _validate_each_entry_override(defaults: Mapping[str, Any], option_key: str,
                                  value: Any, rule: Mapping[str, Any],
                                  owner: str) -> None:
    if not isinstance(value, Mapping):
        raise DesignDslError(f"{owner}.{option_key} must be a mapping")
    default_key = rule["each_entry_extends"]
    if not isinstance(default_key, str) or default_key not in defaults:
        raise DesignDslError(
            f"{owner}.{option_key} merge rule references unknown option "
            f"{default_key!r}")
    default_entry = defaults[default_key]
    if not isinstance(default_entry, Mapping):
        raise DesignDslError(
            f"{owner}.{option_key} merge rule default {default_key!r} must "
            "be a mapping")
    for entry_name, entry_value in value.items():
        if not isinstance(entry_value, Mapping):
            raise DesignDslError(
                f"{owner}.{option_key}.{entry_name} must be a mapping")
        _validate_option_overrides(default_entry, entry_value,
                                   f"{owner}.{option_key}.{entry_name}", {})


def _apply_merge_rules(options: dict[str, Any], merge_rules: Mapping[str, Any],
                       owner: str) -> None:
    remove_options: set[str] = set()
    for option_key, rule in merge_rules.items():
        if not _is_each_entry_extends_rule(rule):
            continue
        if option_key not in options:
            continue
        entry_map = options[option_key]
        if not isinstance(entry_map, Mapping):
            raise DesignDslError(f"{owner}.{option_key} must be a mapping")
        default_key = rule["each_entry_extends"]
        if not isinstance(default_key, str) or default_key not in options:
            raise DesignDslError(
                f"{owner}.{option_key} merge rule references unknown option "
                f"{default_key!r}")
        default_entry = options[default_key]
        if not isinstance(default_entry, Mapping):
            raise DesignDslError(
                f"{owner}.{option_key} merge rule default {default_key!r} "
                "must be a mapping")
        merged_entries = {}
        for entry_name, entry_value in entry_map.items():
            if not isinstance(entry_value, Mapping):
                raise DesignDslError(
                    f"{owner}.{option_key}.{entry_name} must be a mapping")
            merged_entries[entry_name] = _deep_merge(default_entry,
                                                     dict(entry_value))
        options[option_key] = merged_entries
        for key in rule.get("remove_from_resolved_options", []) or []:
            if not isinstance(key, str):
                raise DesignDslError(
                    f"{owner}.{option_key}.remove_from_resolved_options "
                    "entries must be strings")
            remove_options.add(key)
    for key in remove_options:
        options.pop(key, None)
