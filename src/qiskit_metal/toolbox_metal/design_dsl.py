# -*- coding: utf-8 -*-
"""Backward-compatible facade for the native YAML design DSL."""

from __future__ import annotations

from qiskit_metal.toolbox_metal.dsl import (
    BUILTIN_DESIGNS,
    CURRENT_SCHEMA,
    ComponentIR,
    DesignDslError,
    DesignIR,
    NativeComponent,
    PinIR,
    PrimitiveIR,
    DEFAULT_GEOMETRY_OPERATIONS,
    GeometryOperationRegistry,
    build_design,
    build_ir,
    clear_user_registry,
    evaluate_geometry_operations,
    export_ir_to_metal,
    register_design,
    resolve_operation_reference,
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
    "DEFAULT_GEOMETRY_OPERATIONS",
    "GeometryOperationRegistry",
    "evaluate_geometry_operations",
    "resolve_operation_reference",
    "build_ir",
    "export_ir_to_metal",
    "build_design",
    "register_design",
    "clear_user_registry",
]
