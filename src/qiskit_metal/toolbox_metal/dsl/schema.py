# -*- coding: utf-8 -*-
"""Schema constants for the native YAML design DSL v3.

This module declares all keyword sets, kind enumerations, and the
``CURRENT_SCHEMA`` version tag.  It has no imports from this package.
"""

from __future__ import annotations

__all__ = [
    "CURRENT_SCHEMA",
    "ROOT_KEYS",
    "GEOMETRY_KEYS",
    "SIMULATION_KEYS",
    "GMSH_SIM_KEYS",
    "LAYER_STACK_ENTRY_KEYS",
    "LAYER_STACK_KINDS",
    "AIRBOX_KEYS",
    "PORT_KEYS",
    "PORT_TYPES",
    "SYMMETRY_KEYS",
    "SYMMETRY_PLANES",
    "SYMMETRY_CONDITIONS",
    "MESH_KEYS",
    "MESH_REFINE_KEYS",
    "OUTPUT_KEYS",
    "DESIGN_KEYS",
    "TRANSFORM_KEYS",
    "COMPONENT_KEYS",
    "PRIMITIVE_KEYS",
    "PIN_KEYS",
    "GENERATOR_KEYS",
    "NETLIST_KEYS",
    "NETLIST_CONNECTION_KEYS",
    "CHIP_KEYS",
    "CHIP_SIZE_KEYS",
    "BUILTIN_DESIGNS",
]

CURRENT_SCHEMA = "qiskit-metal/design-dsl/3"

ROOT_KEYS = {
    "schema", "vars", "hamiltonian", "circuit", "netlist", "geometry",
    "templates", "simulation",
}
GEOMETRY_KEYS = {"design", "templates", "components", "transforms"}
SIMULATION_KEYS = {"gmsh"}
GMSH_SIM_KEYS = {
    "layer_stack", "airbox", "ports", "symmetry", "mesh", "output",
}
LAYER_STACK_ENTRY_KEYS = {
    "kind", "thickness", "z", "material", "eps_r", "tan_delta",
}
LAYER_STACK_KINDS = {"metal", "dielectric"}
AIRBOX_KEYS = {"top", "bottom", "side_buffer"}
PORT_KEYS = {"pin", "type", "impedance", "value"}
PORT_TYPES = {"lumped", "ground"}
SYMMETRY_KEYS = {"plane", "condition"}
SYMMETRY_PLANES = {"x0", "y0", "z0"}
SYMMETRY_CONDITIONS = {"pec", "pmc"}
MESH_KEYS = {
    "max_size", "min_size", "max_size_jj", "conductor_refine",
}
MESH_REFINE_KEYS = {"min_dist", "max_dist"}
OUTPUT_KEYS = {"format", "scaling"}
DESIGN_KEYS = {
    "class", "metadata", "overwrite_enabled", "enable_renderers", "variables",
    "chip",
}
TRANSFORM_KEYS = {"translate", "rotate", "origin"}
COMPONENT_KEYS = {
    "name", "primitives", "pins", "metadata", "transform", "translate",
    "rotate", "origin", "type", "options", "operations", "generators",
}
PRIMITIVE_KEYS = {
    "name", "kind", "shape", "type", "primitive", "points", "center", "size",
    "subtract", "helper", "layer", "chip", "width", "fillet", "transform",
    "operation",
}
PIN_KEYS = {
    "name", "points", "width", "gap", "chip", "transform", "mode",
    "from_operation", "operation", "segment",
}
GENERATOR_KEYS = {"for_each", "as", "operations", "primitives", "pins"}
NETLIST_KEYS = {"connections"}
NETLIST_CONNECTION_KEYS = {"from", "to"}
CHIP_KEYS = {
    "name", "size", "size_x", "size_y", "size_z", "center_x", "center_y",
    "center_z",
}
CHIP_SIZE_KEYS = {"size_x", "size_y"}

BUILTIN_DESIGNS: dict[str, str] = {
    "DesignPlanar": "qiskit_metal.designs.design_planar.DesignPlanar",
    "DesignFlipChip": "qiskit_metal.designs.design_flipchip.DesignFlipChip",
    "DesignMultiPlanar":
        "qiskit_metal.designs.design_multiplanar.MultiPlanar",
}
