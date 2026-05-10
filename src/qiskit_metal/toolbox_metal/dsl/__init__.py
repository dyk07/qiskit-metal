# -*- coding: utf-8 -*-
"""Public package API for the native YAML design DSL."""

from __future__ import annotations

from .builder import (
    BUILTIN_DESIGNS,
    CURRENT_SCHEMA,
    ComponentIR,
    DesignDslError,
    DesignIR,
    NativeComponent,
    PinIR,
    PrimitiveIR,
    build_design,
    build_ir,
    clear_user_registry,
    export_ir_to_metal,
    register_design,
)
from .component_templates import ComponentTemplateExpansion
from .expression import evaluate_expression, substitute_string, walk_substitute
from .template_model import ComponentTemplate, TEMPLATE_SCHEMA
from .template_registry import (
    BUILTIN_COMPONENT_TEMPLATE_PATHS,
    ComponentTemplateRegistry,
)

__all__ = [
    "DesignDslError",
    "DesignIR",
    "PrimitiveIR",
    "PinIR",
    "ComponentIR",
    "NativeComponent",
    "BUILTIN_DESIGNS",
    "CURRENT_SCHEMA",
    "build_ir",
    "export_ir_to_metal",
    "build_design",
    "register_design",
    "clear_user_registry",
    "ComponentTemplate",
    "ComponentTemplateExpansion",
    "ComponentTemplateRegistry",
    "BUILTIN_COMPONENT_TEMPLATE_PATHS",
    "TEMPLATE_SCHEMA",
    "evaluate_expression",
    "substitute_string",
    "walk_substitute",
]
