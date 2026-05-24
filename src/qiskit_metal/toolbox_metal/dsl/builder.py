# -*- coding: utf-8 -*-
"""Native YAML DSL for Hamiltonian-Circuit-Netlist-Geometry designs.

This module intentionally does not instantiate qlibrary components such as
``TransmonPocket`` or ``RouteMeander``.  The YAML file is first resolved into a
small design IR, then optionally exported to a regular Metal ``QDesign`` by
writing primitive shapely geometry, pins, and net connections directly.

This file is the backward-compatible orchestration layer.  Implementation has
been split into:
  - schema.py       — YAML key/kind constants
  - ir.py           — PrimitiveIR / PinIR / ComponentIR / DesignIR dataclasses
  - parsers/        — parsing sub-package (circuit, geometry, simulation)
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Union

import numpy as np
import yaml

from qiskit_metal import Dict
from qiskit_metal.qlibrary.core.base import QComponent

from ._helpers import (
    UniqueKeyYamlLoader as _UniqueKeyLoader,
    deep_merge as _deep_merge,
    reject_unknown_keys as _reject_unknown_keys,
)
from .errors import DesignDslError
from .expression import walk_substitute as _walk_substitute
from .template_registry import ComponentTemplateRegistry

# ---------------------------------------------------------------------------
# Re-export schema constants (backward compatibility)
# ---------------------------------------------------------------------------
from .schema import *  # noqa: F401, F403
from .schema import (
    BUILTIN_DESIGNS,
    CURRENT_SCHEMA,
    DESIGN_KEYS,
    GEOMETRY_KEYS,
    NETLIST_KEYS,
    ROOT_KEYS,
)

# ---------------------------------------------------------------------------
# Re-export IR types (backward compatibility)
# ---------------------------------------------------------------------------
from .ir import ComponentIR, DesignIR, PinIR, PrimitiveIR  # noqa: F401

# ---------------------------------------------------------------------------
# Re-export parser functions needed by external callers (backward compatibility)
# gmsh_adapter.py imports _parse_gmsh_simulation from .builder
# ---------------------------------------------------------------------------
from .parsers.simulation import _parse_gmsh_simulation  # noqa: F401
from .parsers.geometry import (  # noqa: F401
    _validate_design_spec,
    _design_init_kwargs,
    _parse_components,
    _parse_chip_size,
    _validate_chip_spec,
    _transform_spec,
    _validate_transform,
    _parse_type,
    _layer,
    _apply_transform_to_geometry,
    _apply_transform_to_points,
    _rotate_point,
    _make_primitive_geometry,
    _primitive_from_spec,
    _pin_from_spec,
    _points_from_normal_segment,
    _points_from_normal_points,
    _generator_items,
    _resolve_generator_iterator,
    _expand_component_generators,
    _namespace_generated_operation_refs,
    _components_as_list,
)
from .parsers.circuit import (  # noqa: F401
    _split_endpoint,
    _normalise_connections,
    _bounds_list,
    _derive,
    _validate_netlist_endpoints,
)
from .parsers.simulation import (  # noqa: F401
    _parse_simulation,
    _parse_layer_stack,
    _parse_airbox,
    _parse_ports,
    _parse_symmetry,
    _parse_mesh_settings,
    _parse_output_settings,
    _parse_scalar_with_optional_unit,
    _SIMPLE_UNIT_SUFFIX_RE,
    _ALLOWED_IMPEDANCE_UNITS,
)

__all__ = [
    "DesignDslError",
    "DesignIR",
    "PrimitiveIR",
    "PinIR",
    "ComponentIR",
    "NativeComponent",
    "BUILTIN_DESIGNS",
    "build_ir",
    "export_ir_to_metal",
    "build_design",
    "register_design",
    "clear_user_registry",
]

# ---------------------------------------------------------------------------
# Mutable user-design registry (stays here — mutable module-level state)
# ---------------------------------------------------------------------------
_USER_DESIGNS: dict[str, Any] = {}


def register_design(short_name: str, cls_or_path: Union[type, str]) -> None:
    """Register a QDesign subclass short name for the native DSL."""
    _USER_DESIGNS[short_name] = cls_or_path


def clear_user_registry() -> None:
    """Clear user registered design classes."""
    _USER_DESIGNS.clear()


# ---------------------------------------------------------------------------
# NativeComponent — QComponent subclass; part of the Metal integration layer
# ---------------------------------------------------------------------------
class NativeComponent(QComponent):
    """Minimal Metal component used only to own native DSL geometry."""

    component_metadata = Dict(short_name="N",
                              _qgeometry_table_path="True",
                              _qgeometry_table_poly="True",
                              _qgeometry_table_junction="True")
    TOOLTIP = "Native primitive component"

    def make(self):
        """Native components are populated by the DSL exporter."""


# ---------------------------------------------------------------------------
# Design class resolver (wraps the registry-aware version in parsers.geometry)
# ---------------------------------------------------------------------------
def _resolve_class(name_or_path: str, table: Mapping[str, Any],
                   user_table: Mapping[str, Any], kind: str):
    if not isinstance(name_or_path, str) or not name_or_path:
        raise DesignDslError(f"{kind} class must be a non-empty string")

    target = user_table.get(name_or_path) or table.get(name_or_path)
    if target is None:
        raise DesignDslError(f"Unknown {kind} short name: {name_or_path!r}")

    if not isinstance(target, str):
        return target
    if "." not in target:
        raise DesignDslError(f"Unknown {kind} short name: {name_or_path!r}")

    module_path, attr_name = target.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise DesignDslError(
            f"Cannot import {kind} module {module_path!r}: {exc}") from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        raise DesignDslError(
            f"Module {module_path!r} has no {kind} class {attr_name!r}") from exc


def _resolve_design_class(design_spec: Mapping[str, Any]):
    """Resolve design class using the global registries."""
    class_name = design_spec.get("class", "DesignPlanar")
    return _resolve_class(class_name, BUILTIN_DESIGNS, _USER_DESIGNS, "design")


def _design_variable_context(design_spec: Mapping[str, Any],
                              root_vars: Mapping[str, Any]) -> dict[str, Any]:
    """Return variables visible to DSL numeric parsing."""
    from .parsers.geometry import (
        _validate_design_spec as _vds,
        _design_init_kwargs as _dik,
        _optional_mapping as _om,
    )
    _vds(design_spec)
    design_cls = _resolve_design_class(design_spec)
    init_kwargs = _dik(design_spec)
    init_kwargs["enable_renderers"] = False
    design = design_cls(**init_kwargs)
    return {
        **dict(design.variables),
        **_om(design_spec, "variables"),
        **dict(root_vars),
    }


def _instantiate_design(design_spec: Mapping[str, Any]):
    """Instantiate the QDesign described in *design_spec*."""
    from .parsers.geometry import (
        _validate_design_spec as _vds,
        _design_init_kwargs as _dik,
        _validate_chip_spec as _vcs,
        _parse_chip_size as _pcs,
        _optional_mapping as _om,
    )
    _vds(design_spec)
    design_cls = _resolve_design_class(design_spec)
    design = design_cls(**_dik(design_spec))
    for key, value in _om(design_spec, "variables").items():
        design.variables[key] = value

    chip_spec = _om(design_spec, "chip")
    if chip_spec:
        _vcs(chip_spec)
        chip_name = chip_spec.get("name", "main")
        if chip_name not in design.chips:
            raise DesignDslError(f"design has no chip {chip_name!r}")
        chip_size = design.chips[chip_name]["size"]
        if "size" in chip_spec:
            size_x, size_y = _pcs(chip_spec["size"])
            if size_x is not None:
                chip_size["size_x"] = size_x
            if size_y is not None:
                chip_size["size_y"] = size_y
        for key in ("size_x", "size_y", "size_z", "center_x", "center_y",
                    "center_z"):
            if key in chip_spec:
                chip_size[key] = chip_spec[key]
    return design


# ---------------------------------------------------------------------------
# YAML loading helpers
# ---------------------------------------------------------------------------
def _load_yaml(source: Union[str, Path]) -> tuple[dict, Optional[Path]]:
    if isinstance(source, Path):
        return _load_yaml_file(source)

    if isinstance(source, str):
        candidate = Path(source)
        if "\n" not in source and len(source) < 4096 and candidate.exists():
            return _load_yaml_file(candidate)
        try:
            data = yaml.load(source, Loader=_UniqueKeyLoader)
        except yaml.YAMLError as exc:
            raise DesignDslError(f"YAML parse failed: {exc}") from exc
        if not isinstance(data, dict):
            raise DesignDslError("DSL document must be a mapping")
        return data, None

    raise DesignDslError(
        f"build_ir accepts Path or str, got {type(source).__name__}")


def _load_yaml_file(path: Path) -> tuple[dict, Path]:
    if not path.exists():
        raise DesignDslError(f"DSL file does not exist: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.load(handle, Loader=_UniqueKeyLoader)
    except yaml.YAMLError as exc:
        raise DesignDslError(f"YAML parse failed ({path}): {exc}") from exc
    if not isinstance(data, dict):
        raise DesignDslError(f"DSL document must be a mapping ({path})")
    return data, path.parent


def _expand_includes(node: Any,
                     base_dir: Optional[Path],
                     seen: Optional[frozenset[Path]] = None) -> Any:
    seen = seen or frozenset()
    if isinstance(node, dict):
        if set(node.keys()) == {"$include"}:
            include_path = node["$include"]
            if not isinstance(include_path, str):
                raise DesignDslError("$include value must be a string path")
            if base_dir is None:
                raise DesignDslError(
                    "$include requires build_ir to receive a file path")
            target = (base_dir / include_path).resolve()
            if target in seen:
                chain = " -> ".join(str(path) for path in [*seen, target])
                raise DesignDslError(f"$include cycle detected: {chain}")
            included, child_dir = _load_yaml_file(target)
            return _expand_includes(included, child_dir, seen | {target})
        return {
            key: _expand_includes(val, base_dir, seen)
            for key, val in node.items()
        }
    if isinstance(node, list):
        return [_expand_includes(item, base_dir, seen) for item in node]
    return node


# ---------------------------------------------------------------------------
# Template expansion helpers (used by build_ir orchestration)
# ---------------------------------------------------------------------------
def _resolve_template(name: str, templates: Mapping[str, Any],
                      seen: frozenset[str]) -> dict:
    if name in seen:
        raise DesignDslError(f"$extend cycle detected at {name!r}")
    if name not in templates:
        raise DesignDslError(
            f"Unknown template {name!r}; known templates: {sorted(templates)}")
    template = templates[name]
    if not isinstance(template, dict):
        raise DesignDslError(f"Template {name!r} must be a mapping")
    if "$extend" in template:
        parent_name = template["$extend"]
        if not isinstance(parent_name, str):
            raise DesignDslError(
                f"Template {name!r} $extend value must be a template name")
        parent = _resolve_template(parent_name, templates, seen | {name})
        body = {key: val for key, val in template.items() if key != "$extend"}
        return _deep_merge(parent, body)
    return dict(template)


def _expand_node(node: Any, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list[Any]:
    if not isinstance(node, dict):
        return [_walk_substitute(node, ctx)]

    if "$for" in node:
        iter_list = node["$for"]
        if not isinstance(iter_list, list):
            raise DesignDslError("$for value must be a list")
        body = {key: val for key, val in node.items() if key != "$for"}
        results: list[Any] = []
        for index, iter_vars in enumerate(iter_list):
            if not isinstance(iter_vars, dict):
                raise DesignDslError(f"$for[{index}] must be a mapping")
            resolved_iter = _walk_substitute(iter_vars, ctx)
            results.extend(
                _expand_node(body, {**ctx, **resolved_iter}, templates))
        return results

    if "$extend" in node:
        template_name = node["$extend"]
        if not isinstance(template_name, str):
            raise DesignDslError("$extend value must be a template name")
        template = _resolve_template(template_name, templates, frozenset())
        body = {key: val for key, val in node.items() if key != "$extend"}
        return _expand_node(_deep_merge(template, body), ctx, templates)

    return [_walk_substitute(node, ctx)]


def _expand_list(items: list, ctx: Mapping[str, Any],
                 templates: Mapping[str, Any]) -> list:
    if not isinstance(items, list):
        raise DesignDslError("Expandable DSL field must be a list")
    out: list[Any] = []
    for item in items:
        out.extend(_expand_node(item, ctx, templates))
    return out


# ---------------------------------------------------------------------------
# Small orchestration utilities
# ---------------------------------------------------------------------------
def _optional_mapping(container: Mapping[str, Any], key: str) -> dict:
    if key not in container:
        return {}
    value = container[key]
    if not isinstance(value, Mapping):
        raise DesignDslError(f"{key} must be a mapping")
    return dict(value)


def _optional_list(container: Mapping[str, Any], key: str) -> list:
    if key not in container:
        return []
    value = container[key]
    if not isinstance(value, list):
        raise DesignDslError(f"{key} must be a list")
    return value


# ---------------------------------------------------------------------------
# Main orchestration: build_ir
# ---------------------------------------------------------------------------
def build_ir(source: Union[str, Path],
             *,
             overrides: Optional[Mapping[str, Any]] = None) -> DesignIR:
    """Build a resolved native v3 IR from a YAML file or YAML text."""
    spec, base_dir = _load_yaml(source)
    spec = _expand_includes(spec, base_dir)
    if overrides:
        spec = _deep_merge(spec, dict(overrides))

    _reject_unknown_keys(spec, ROOT_KEYS, "root")

    schema = spec.get("schema")
    if schema != CURRENT_SCHEMA:
        raise DesignDslError(
            f"Unsupported schema {schema!r}; expected {CURRENT_SCHEMA!r}")

    geometry_spec = spec.get("geometry")
    if not isinstance(geometry_spec, Mapping):
        raise DesignDslError("geometry must be a mapping")
    _reject_unknown_keys(geometry_spec, GEOMETRY_KEYS, "geometry")
    design_spec = geometry_spec.get("design")
    if not isinstance(design_spec, Mapping):
        raise DesignDslError("geometry.design must be a mapping")
    _reject_unknown_keys(design_spec, DESIGN_KEYS, "geometry.design")

    vars_table = _optional_mapping(spec, "vars")
    ctx_vars = {**vars_table, "vars": vars_table}
    circuit = _walk_substitute(_optional_mapping(spec, "circuit"), ctx_vars)
    hamiltonian = _walk_substitute(
        _optional_mapping(spec, "hamiltonian"),
        {**ctx_vars, "circuit": circuit},
    )
    netlist_spec = None
    if "netlist" in spec:
        netlist_spec = spec["netlist"]
        if not isinstance(netlist_spec, Mapping):
            raise DesignDslError("netlist must be a mapping")
        _reject_unknown_keys(netlist_spec, NETLIST_KEYS, "netlist")
    netlist = _walk_substitute(
        dict(netlist_spec or {}),
        {**ctx_vars, "circuit": circuit, "hamiltonian": hamiltonian},
    )
    ctx = {
        **vars_table,
        "vars": vars_table,
        "circuit": circuit,
        "hamiltonian": hamiltonian,
        "netlist": netlist,
    }

    resolved_geometry = dict(geometry_spec)
    resolved_geometry["design"] = _walk_substitute(geometry_spec["design"], ctx)
    if "transforms" in geometry_spec:
        resolved_geometry["transforms"] = _walk_substitute(
            geometry_spec["transforms"], ctx)
    design_spec = dict(resolved_geometry["design"])
    _validate_design_spec(design_spec)
    variable_context = _design_variable_context(design_spec, vars_table)
    component_ctx = {
        **variable_context,
        "vars": variable_context,
        "circuit": circuit,
        "hamiltonian": hamiltonian,
        "netlist": netlist,
    }
    templates = _deep_merge(_optional_mapping(spec, "templates"),
                            _optional_mapping(resolved_geometry, "templates"))
    template_registry = ComponentTemplateRegistry(templates, base_dir=base_dir)
    components = _parse_components(resolved_geometry, component_ctx, templates,
                                   template_registry, variable_context)
    derived = _derive(components, netlist)
    _validate_netlist_endpoints(components, derived["netlist"]["connections"])

    metadata_geometry = {
        "design": design_spec,
        "templates": templates,
        "components": {
            component.name: component.source for component in components
        },
    }
    if "transforms" in resolved_geometry:
        metadata_geometry["transforms"] = resolved_geometry["transforms"]

    simulation = _parse_simulation(spec.get("simulation"), ctx,
                                   variable_context, components)

    return DesignIR(schema=schema,
                    vars=vars_table,
                    hamiltonian=hamiltonian,
                    circuit=circuit,
                    netlist=netlist,
                    design=design_spec,
                    components=components,
                    geometry=metadata_geometry,
                    derived=derived,
                    simulation=simulation)


# ---------------------------------------------------------------------------
# Metal integration layer
# ---------------------------------------------------------------------------
def _component_pin_names(component: ComponentIR) -> set[str]:
    return {pin.name for pin in component.pins}


def _validate_component_chips(design, component_ir: ComponentIR) -> None:
    known_chips = set(design.chips.keys())
    for primitive in component_ir.primitives:
        if primitive.chip not in known_chips:
            raise DesignDslError(
                f"Primitive {component_ir.name}.{primitive.name} references "
                f"unknown chip {primitive.chip!r}")
    for pin in component_ir.pins:
        if pin.chip not in known_chips:
            raise DesignDslError(
                f"Pin {component_ir.name}.{pin.name} references unknown chip "
                f"{pin.chip!r}")


def export_ir_to_metal(
    ir: DesignIR,
    *,
    post_build: Optional[Callable[[Any], None]] = None,
):
    """Export a native IR into a regular Metal QDesign."""
    design = _instantiate_design(ir.design)
    component_objects: dict[str, NativeComponent] = {}
    component_irs = {component.name: component for component in ir.components}

    for component_ir in ir.components:
        _validate_component_chips(design, component_ir)
        component = NativeComponent(design, component_ir.name, make=False)
        component.metadata.update(component_ir.metadata)
        component_objects[component_ir.name] = component

        for primitive in component_ir.primitives:
            options = dict(primitive.options)
            if primitive.width is not None:
                options["width"] = primitive.width
            if primitive.fillet is not None:
                options["fillet"] = primitive.fillet
            if primitive.kind in component.qgeometry_table_usage:
                component.qgeometry_table_usage[primitive.kind] = True
            design.qgeometry.add_qgeometry(primitive.kind,
                                           component.id, {
                                               primitive.name:
                                                   primitive.geometry
                                           },
                                           subtract=primitive.subtract,
                                           helper=primitive.helper,
                                           layer=primitive.layer,
                                           chip=primitive.chip,
                                           **options)

        for pin in component_ir.pins:
            pin_points = pin.normal_points if pin.input_as_norm else pin.points
            component.add_pin(pin.name,
                              np.array(pin_points, dtype=float),
                              pin.width,
                              input_as_norm=pin.input_as_norm,
                              chip=pin.chip,
                              gap=pin.gap)

    for connection in ir.derived["netlist"]["connections"]:
        from_pin = connection["from"]
        to_pin = connection["to"]
        for endpoint in (from_pin, to_pin):
            comp_name = endpoint["component"]
            pin_name = endpoint["pin"]
            if comp_name not in component_objects:
                raise DesignDslError(
                    f"netlist references unknown component {comp_name!r}")
            if pin_name not in _component_pin_names(component_irs[comp_name]):
                raise DesignDslError(
                    f"netlist references unknown pin {comp_name}.{pin_name}")

        net_id = design.connect_pins(component_objects[from_pin["component"]].id,
                                     from_pin["pin"],
                                     component_objects[to_pin["component"]].id,
                                     to_pin["pin"])
        if not net_id:
            raise DesignDslError(
                f"Could not connect {from_pin} to {to_pin}; pin may be in use")
        connection["net_id"] = int(net_id)

    design.metadata["dsl_chain"] = ir.to_metadata()
    if post_build is not None:
        post_build(design)
    return design


def build_design(
    source: Union[str, Path],
    *,
    overrides: Optional[Mapping[str, Any]] = None,
    post_build: Optional[Callable[[Any], None]] = None,
):
    """Build a Metal QDesign by resolving v3 YAML into IR, then exporting it."""
    ir = build_ir(source, overrides=overrides)
    return export_ir_to_metal(ir, post_build=post_build)
