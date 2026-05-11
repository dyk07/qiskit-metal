# -*- coding: utf-8 -*-

# This code is part of Qiskit.
#
# (C) Copyright IBM 2017, 2021.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

# pylint: disable=protected-access
# pylint: disable-msg=relative-beyond-top-level
# pylint: disable-msg=broad-except
"""Saving and loading Metal designs.

This module defines the canonical JSON text schema for Metal design exchange.

Top-level schema:
    {
        "format": "qiskit-metal.design-description",
        "version": 1,
        "generated_utc": "<ISO8601 UTC timestamp>",
        "design": {...},
        "components": [...],
        "connections": [...]
    }

The text schema is intentionally explicit and stable enough to hand off to
other tools, while remaining compatible with the in-repo design loader.
"""

from datetime import datetime
import importlib
import inspect
import json
import pickle

import numpy as np

from qiskit_metal.toolbox_python.utility_functions import log_error_easy

__all__ = [
    'DESIGN_DESCRIPTION_FORMAT',
    'DESIGN_DESCRIPTION_VERSION',
    'describe_metal_design',
    'describe_metal_text',
    'validate_design_payload',
    'save_metal',
    'save_metal_json',
    'load_metal_design',
    'load_metal_json'
]


DESIGN_DESCRIPTION_FORMAT = 'qiskit-metal.design-description'
DESIGN_DESCRIPTION_VERSION = 1
_TEXT_SERIALIZATION_SUFFIXES = ('.json', '.txt')


def _is_text_serialization_path(filename: str) -> bool:
    """Return True when filename implies text-based Metal serialization."""
    return str(filename).lower().endswith(_TEXT_SERIALIZATION_SUFFIXES)


def _to_jsonable(value):
    """Convert common Metal values into plain JSON-serializable Python types."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, np.ndarray):
        return [_to_jsonable(item) for item in value.tolist()]

    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]

    if hasattr(value, 'tolist'):
        try:
            return _to_jsonable(value.tolist())
        except Exception:
            pass

    return str(value)


def _extract_init_kwargs(instance, ignore_names):
    """Extract constructor kwargs from instance attributes when possible."""
    extracted = {}
    signature = inspect.signature(instance.__class__.__init__)

    for _, param in signature.parameters.items():
        if param.name in ignore_names:
            continue

        attr_name = param.name
        private_attr_name = f'_{param.name}'

        if attr_name in instance.__dict__:
            extracted[attr_name] = _to_jsonable(instance.__dict__[attr_name])
        elif private_attr_name in instance.__dict__:
            extracted[attr_name] = _to_jsonable(
                instance.__dict__[private_attr_name])

    return extracted


def _serialize_connections(design):
    """Serialize pin-to-pin net connections using component names."""
    connections = []

    if design.net_info.empty:
        return connections

    grouped = design.net_info.groupby('net_id')
    for net_id, group in grouped:
        endpoints = []
        for _, row in group.iterrows():
            try:
                component_id = int(row['component_id'])
            except Exception:
                continue

            if component_id not in design._components:
                continue

            endpoints.append({
                'component': design._components[component_id].name,
                'pin': str(row['pin_name'])
            })

        if len(endpoints) == 2:
            connections.append({'net_id': int(net_id), 'endpoints': endpoints})

    return connections


def describe_metal_design(design):
    """Build a JSON-safe design description that obeys the text schema."""
    design_class = f'{design.__class__.__module__}.{design.__class__.__name__}'
    design_init_kwargs = _extract_init_kwargs(
        design,
        ignore_names={
            'self', 'metadata', 'overwrite_enabled', 'enable_renderers',
            'kwargs', 'args'
        })

    components = []
    for component_id in sorted(design._components.keys()):
        component = design._components[component_id]
        component_init_kwargs = _extract_init_kwargs(
            component,
            ignore_names={
                'self', 'design', 'name', 'options', 'make',
                'component_template', 'kwargs', 'args'
            })

        components.append({
            'id': int(component_id),
            'name': component.name,
            'class': component.class_name,
            'made': bool(getattr(component, '_made', False)),
            'status': str(getattr(component, 'status', '')),
            'options': _to_jsonable(component.options),
            'metadata': _to_jsonable(component.metadata),
            'pins': _to_jsonable(component.pins),
            'init_kwargs': component_init_kwargs
        })

    payload = {
        'format': DESIGN_DESCRIPTION_FORMAT,
        'version': DESIGN_DESCRIPTION_VERSION,
        'generated_utc':
        datetime.utcnow().isoformat(timespec='seconds') + 'Z',
        'design': {
            'class': design_class,
            'name': str(getattr(design, 'name', 'Design')),
            'save_path': _to_jsonable(getattr(design, 'save_path', None)),
            'overwrite_enabled': bool(
                getattr(design, 'overwrite_enabled', False)),
            'enable_renderers': bool(getattr(design, '_renderers', {})),
            'metadata': _to_jsonable(design.metadata),
            'variables': _to_jsonable(design.variables),
            'chips': _to_jsonable(design.chips),
            'init_kwargs': design_init_kwargs
        },
        'components': components,
        'connections': _serialize_connections(design)
    }

    validate_design_payload(payload)
    return payload


def describe_metal_text(design, indent: int = 2) -> str:
    """Return a deterministic plain-text JSON design description."""
    payload = describe_metal_design(design)
    return json.dumps(payload, indent=indent, sort_keys=True)


def _require_type(value, expected_type, path: str):
    """Raise a ValueError when value does not match expected_type."""
    if not isinstance(value, expected_type):
        expected_name = expected_type.__name__
        actual_name = type(value).__name__
        raise ValueError(f'Invalid schema at {path}: expected {expected_name}, '
                         f'got {actual_name}.')


def validate_design_payload(payload: dict):
    """Validate the canonical JSON design schema.

    This is a lightweight validator for the required structure. It intentionally
    checks schema shape rather than every nested option type.
    """
    _require_type(payload, dict, 'payload')

    required_top_level = {
        'format': str,
        'version': int,
        'generated_utc': str,
        'design': dict,
        'components': list,
        'connections': list
    }
    for key, expected in required_top_level.items():
        if key not in payload:
            raise ValueError(f'Invalid schema: missing top-level key "{key}".')
        _require_type(payload[key], expected, key)

    if payload['format'] != DESIGN_DESCRIPTION_FORMAT:
        raise ValueError('Invalid schema: unsupported "format" value.')
    if payload['version'] != DESIGN_DESCRIPTION_VERSION:
        raise ValueError('Invalid schema: unsupported "version" value.')

    design = payload['design']
    for key, expected in {
            'class': str,
            'name': str,
            'save_path': (str, type(None)),
            'overwrite_enabled': bool,
            'enable_renderers': bool,
            'metadata': dict,
            'variables': dict,
            'chips': dict,
            'init_kwargs': dict
    }.items():
        if key not in design:
            raise ValueError(f'Invalid schema: missing design key "{key}".')
        if not isinstance(design[key], expected):
            expected_name = getattr(expected, '__name__', str(expected))
            actual_name = type(design[key]).__name__
            raise ValueError(f'Invalid schema at design.{key}: expected '
                             f'{expected_name}, got {actual_name}.')

    for index, component in enumerate(payload['components']):
        _require_type(component, dict, f'components[{index}]')
        for key, expected in {
                'id': int,
                'name': str,
                'class': str,
                'made': bool,
                'status': str,
                'options': dict,
                'metadata': dict,
                'pins': dict,
                'init_kwargs': dict
        }.items():
            if key not in component:
                raise ValueError('Invalid schema: missing component key '
                                 f'"{key}" in components[{index}].')
            _require_type(component[key], expected,
                          f'components[{index}].{key}')

    for index, connection in enumerate(payload['connections']):
        _require_type(connection, dict, f'connections[{index}]')
        if 'net_id' not in connection or 'endpoints' not in connection:
            raise ValueError('Invalid schema: each connection must contain '
                             '"net_id" and "endpoints".')
        _require_type(connection['net_id'], int, f'connections[{index}].net_id')
        _require_type(connection['endpoints'], list,
                      f'connections[{index}].endpoints')
        if len(connection['endpoints']) != 2:
            raise ValueError('Invalid schema: each connection must have exactly '
                             '2 endpoints.')
        for end_index, endpoint in enumerate(connection['endpoints']):
            _require_type(endpoint, dict,
                          f'connections[{index}].endpoints[{end_index}]')
            for key in ('component', 'pin'):
                if key not in endpoint:
                    raise ValueError('Invalid schema: missing endpoint key '
                                     f'"{key}".')
                _require_type(endpoint[key], str,
                              f'connections[{index}].endpoints[{end_index}].'
                              f'{key}')


def save_metal_json(filename: str, design, indent: int = 2):
    """Save design to a JSON text file that obeys the canonical schema."""
    result = False

    self = design
    logger = self.logger
    self.logger = None

    try:
        payload = describe_metal_design(self)
        with open(filename, 'w', encoding='utf-8') as outfile:
            json.dump(payload, outfile, indent=indent, sort_keys=True)
            outfile.write('\n')
        result = True
    except Exception as e:
        text = f'ERROR WHILE SAVING JSON DESIGN: {e}'
        log_error_easy(logger, post_text=text)
        result = False

    self.logger = logger
    return result


def _import_symbol(class_path: str):
    """Import and return symbol from fully-qualified class path."""
    module_path, class_name = class_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _instantiate_design_from_payload(payload_design: dict):
    """Instantiate concrete QDesign subclass from serialized payload."""
    design_class_path = payload_design.get(
        'class', 'qiskit_metal.designs.design_planar.DesignPlanar')
    design_metadata = payload_design.get('metadata', {})
    init_kwargs = payload_design.get('init_kwargs', {})

    design_class = _import_symbol(design_class_path)

    constructor_kwargs = {
        'metadata': design_metadata,
        'overwrite_enabled': bool(payload_design.get('overwrite_enabled',
                                                     False)),
        'enable_renderers': bool(payload_design.get('enable_renderers', True)),
        **init_kwargs
    }

    try:
        return design_class(**constructor_kwargs)
    except TypeError:
        constructor_kwargs.pop('overwrite_enabled', None)
        constructor_kwargs.pop('enable_renderers', None)
        try:
            return design_class(**constructor_kwargs)
        except TypeError:
            return design_class(metadata=design_metadata)


def _restore_pin_arrays(pin_dict: dict) -> dict:
    """Restore common pin fields back to numpy arrays for compatibility."""
    array_keys = {'points', 'middle', 'normal', 'tangent'}
    restored = {}

    for key, value in pin_dict.items():
        if key in array_keys and isinstance(value, list):
            try:
                restored[key] = np.array(value)
            except Exception:
                restored[key] = value
        else:
            restored[key] = value

    return restored


def _restore_component_options(options):
    """Restore JSON-safe option values back to Metal-friendly structures."""
    if isinstance(options, dict):
        restored = {}
        for key, value in options.items():
            if key == 'anchors' and isinstance(value, dict):
                restored[key] = {}
                for anchor_key, anchor_value in value.items():
                    if isinstance(anchor_value, list):
                        try:
                            restored[key][anchor_key] = np.array(anchor_value,
                                                                 dtype=float)
                            continue
                        except (TypeError, ValueError):
                            pass
                    restored[key][anchor_key] = _restore_component_options(
                        anchor_value)
            else:
                restored[key] = _restore_component_options(value)
        return restored

    if isinstance(options, list):
        return [_restore_component_options(item) for item in options]

    return options


def _deserialize_components(design, payload_components: list):
    """Instantiate and restore serialized components on a design."""
    for component_data in payload_components:
        class_path = component_data.get('class')
        if not class_path:
            continue

        component_class = _import_symbol(class_path)

        name = component_data.get('name')
        options = _restore_component_options(component_data.get('options', {}))
        make = bool(component_data.get('made', True))
        init_kwargs = component_data.get('init_kwargs', {})

        try:
            component = component_class(design,
                                        name=name,
                                        options=options,
                                        make=make,
                                        **init_kwargs)
        except TypeError:
            try:
                component = component_class(design,
                                            name=name,
                                            options=options,
                                            make=make)
            except TypeError:
                try:
                    component = component_class(design,
                                                name=name,
                                                options=options,
                                                **init_kwargs)
                except TypeError:
                    component = component_class(design,
                                                name=name,
                                                options=options)

        if 'metadata' in component_data and isinstance(component_data['metadata'],
                                                       dict):
            component.metadata.update(component_data['metadata'])

        serialized_pins = component_data.get('pins', {})
        if isinstance(serialized_pins,
                      dict) and (not make or len(component.pins) == 0):
            component.pins.clear()
            for pin_name, pin_values in serialized_pins.items():
                if isinstance(pin_values, dict):
                    component.pins[pin_name] = _restore_pin_arrays(pin_values)
                else:
                    component.pins[pin_name] = pin_values


def _deserialize_connections(design, payload_connections: list):
    """Replay serialized net connections after components are instantiated."""
    design.delete_all_pins()

    for connection in payload_connections:
        endpoints = connection.get('endpoints', [])
        if len(endpoints) != 2:
            continue

        end_a, end_b = endpoints
        comp_a_name = end_a.get('component')
        comp_b_name = end_b.get('component')
        pin_a_name = end_a.get('pin')
        pin_b_name = end_b.get('pin')

        comp_a_id = design.components.find_id(comp_a_name, quiet=True)
        comp_b_id = design.components.find_id(comp_b_name, quiet=True)
        if not comp_a_id or not comp_b_id:
            continue

        if pin_a_name not in design._components[comp_a_id].pins:
            continue
        if pin_b_name not in design._components[comp_b_id].pins:
            continue

        design.connect_pins(comp_a_id, pin_a_name, comp_b_id, pin_b_name)


def load_metal_json(filename: str):
    """Load a design from a schema-valid JSON/text Metal description file."""
    with open(filename, 'r', encoding='utf-8') as infile:
        payload = json.load(infile)

    validate_design_payload(payload)

    payload_design = payload.get('design', {})
    design = _instantiate_design_from_payload(payload_design)

    if 'metadata' in payload_design and isinstance(payload_design['metadata'],
                                                   dict):
        design.update_metadata(payload_design['metadata'])

    if 'variables' in payload_design and isinstance(payload_design['variables'],
                                                    dict):
        design.variables.clear()
        design.variables.update(payload_design['variables'])

    if 'chips' in payload_design and isinstance(payload_design['chips'], dict):
        design.chips.clear()
        design.chips.update(payload_design['chips'])

    _deserialize_components(design, payload.get('components', []))
    _deserialize_connections(design, payload.get('connections', []))

    design.save_path = str(filename)
    from .. import logger
    design.logger = logger

    return design


def save_metal(filename: str, design):
    """Save a Metal design.

    `.json` and `.txt` emit the canonical text schema.
    Other extensions retain pickle behavior for legacy compatibility.
    """
    if _is_text_serialization_path(filename):
        return save_metal_json(filename, design)

    result = False

    self = design
    logger = self.logger
    self.logger = None

    try:
        with open(filename, 'wb') as outfile:
            pickle.dump(self, outfile)
        result = True
    except Exception as e:
        text = f'ERROR WHILE SAVING: {e}'
        log_error_easy(logger, post_text=text)
        result = False

    self.logger = logger
    return result


def load_metal_design(filename: str):
    """Load a Metal design from either the text schema or legacy pickle."""
    if _is_text_serialization_path(filename):
        return load_metal_json(filename)

    with open(filename, 'rb') as infile:
        design = pickle.load(infile)

    design.save_path = str(filename)

    from .. import logger
    design.logger = logger

    return design
