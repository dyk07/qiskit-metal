# -*- coding: utf-8 -*-
"""Shared internal helpers for the native YAML design DSL.

Kept private (leading underscore) so external code does not depend on them.
"""

from __future__ import annotations

from numbers import Number
from typing import Any, Mapping, Optional

import numpy as np
import yaml

from qiskit_metal.toolbox_metal.parsing import parse_value

from .errors import DesignDslError


class UniqueKeyYamlLoader(yaml.SafeLoader):
    """YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(loader: UniqueKeyYamlLoader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise DesignDslError(f"Duplicate YAML mapping key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyYamlLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def deep_merge(base: Any, override: Any) -> Any:
    """Recursively merge two mappings; ``override`` wins on conflicts."""
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for key, value in override.items():
            out[key] = deep_merge(out.get(key), value) if key in out else value
        return out
    return override


def reject_unknown_keys(spec: Mapping[str, Any], allowed: set[str],
                        owner: str) -> None:
    """Raise ``DesignDslError`` if ``spec`` has keys outside ``allowed``."""
    unknown = set(spec) - allowed
    if unknown:
        raise DesignDslError(f"Unknown {owner} key(s): {sorted(unknown)}")


def parse_number(value: Any,
                 variables: Optional[Mapping[str, Any]] = None,
                 owner: str = "value") -> float:
    """Parse a numeric value (with optional units) to float."""
    if isinstance(value, bool):
        raise DesignDslError(
            f"{owner} must be a numeric value with optional units, got "
            f"{value!r}")
    try:
        parsed = parse_value(value, dict(variables or {}))
    except Exception as exc:
        raise DesignDslError(
            f"{owner} must be a numeric value with optional units, got "
            f"{value!r}: {exc}") from exc
    if isinstance(parsed, (int, float, np.number)) and not isinstance(
            parsed, bool):
        return float(parsed)
    raise DesignDslError(
        f"{owner} must be a numeric value with optional units, got {value!r}")


def parse_optional_number(value: Any,
                          variables: Optional[Mapping[str, Any]] = None,
                          owner: str = "value") -> Optional[float]:
    if value is None:
        return None
    return parse_number(value, variables, owner)


def parse_point(value: Any,
                variables: Optional[Mapping[str, Any]] = None,
                owner: str = "Point") -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise DesignDslError(f"{owner} must be [x, y], got {value!r}")
    return [
        parse_number(value[0], variables, f"{owner}[0]"),
        parse_number(value[1], variables, f"{owner}[1]"),
    ]


def parse_points(value: Any,
                 variables: Optional[Mapping[str, Any]] = None,
                 owner: str = "points") -> list[list[float]]:
    if not isinstance(value, list) or len(value) < 2:
        raise DesignDslError(f"{owner} must be a list with at least two points")
    return [
        parse_point(point, variables, f"{owner}[{index}]")
        for index, point in enumerate(value)
    ]


def parse_angle(value: Any, owner: str = "Angle") -> float:
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


def parse_bool(value: Any, owner: str = "value") -> bool:
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
    raise DesignDslError(
        f"{owner} must be a boolean or one of true/false/yes/no/1/0, "
        f"got {value!r}")
