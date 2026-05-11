# -*- coding: utf-8 -*-
"""Component template lookup for the native YAML design DSL."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import yaml

from ._helpers import UniqueKeyYamlLoader
from .errors import DesignDslError
from .template_model import (
    TEMPLATE_SCHEMA,
    ComponentTemplate,
    component_template_from_mapping,
)


BUILTIN_COMPONENT_TEMPLATE_PATHS = {
    "qcomponent": Path("core/qcomponent.yaml"),
    "base_qubit": Path("core/base_qubit.yaml"),
    "transmon_pocket": Path("qubits/transmon_pocket.yaml"),
}


class ComponentTemplateRegistry:
    """Resolve component templates from inline maps, built-ins, and files."""

    def __init__(self,
                 inline_templates: Optional[Mapping[str, Any]] = None,
                 *,
                 base_dir: Optional[Path] = None):
        self.base_dir = base_dir
        self._inline_specs = {
            key: value
            for key, value in (inline_templates or {}).items()
            if isinstance(value, Mapping)
            and value.get("schema") == TEMPLATE_SCHEMA
        }
        self._cache: dict[str, ComponentTemplate] = {}

    def resolve(self,
                template_id: str,
                seen: Optional[frozenset[str]] = None) -> ComponentTemplate:
        """Return a template by id, rejecting cycles through ``extends``."""
        if not isinstance(template_id, str) or not template_id:
            raise DesignDslError("component type must be a non-empty string")
        seen = seen or frozenset()
        if template_id in seen:
            raise DesignDslError(
                f"component template extends cycle detected at {template_id!r}")
        if template_id in self._cache:
            return self._cache[template_id]

        spec = self._load_template_spec(template_id)
        template = component_template_from_mapping(spec,
                                                   f"component template "
                                                   f"{template_id!r}")
        if template.id != template_id:
            raise DesignDslError(
                f"component template {template_id!r} declares id "
                f"{template.id!r}")
        if template.extends is not None:
            self.resolve(template.extends, seen | {template_id})
        self._cache[template_id] = template
        return template

    def inheritance_chain(self, template_id: str) -> list[ComponentTemplate]:
        """Return parent templates first, ending with ``template_id``."""
        template = self.resolve(template_id)
        if template.extends is None:
            return [template]
        return [*self.inheritance_chain(template.extends), template]

    def _load_template_spec(self, template_id: str) -> Mapping[str, Any]:
        if template_id in self._inline_specs:
            return self._inline_specs[template_id]

        if template_id in BUILTIN_COMPONENT_TEMPLATE_PATHS:
            path = _builtin_template_root() / BUILTIN_COMPONENT_TEMPLATE_PATHS[
                template_id]
            if not path.exists():
                raise DesignDslError(
                    f"Built-in component template {template_id!r} is not "
                    f"available yet ({path})")
            return _load_template_file(path)

        if self.base_dir is not None:
            candidate = (self.base_dir / template_id).resolve()
            if candidate.exists() and candidate.is_file():
                return _load_template_file(candidate)

        known = sorted(
            set(self._inline_specs) | set(BUILTIN_COMPONENT_TEMPLATE_PATHS))
        raise DesignDslError(
            f"Unknown component template type {template_id!r}; known templates: "
            f"{known}")


def _builtin_template_root() -> Path:
    return Path(__file__).resolve().parent.parent / "dsl_templates"


def _load_template_file(path: Path) -> Mapping[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=UniqueKeyYamlLoader)
    except yaml.YAMLError as exc:
        raise DesignDslError(f"YAML parse failed ({path}): {exc}") from exc
    if not isinstance(data, Mapping):
        raise DesignDslError(f"component template must be a mapping ({path})")
    return data
