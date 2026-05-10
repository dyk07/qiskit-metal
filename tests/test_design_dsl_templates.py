# -*- coding: utf-8 -*-
"""Tests for YAML-native component templates in the v3 design DSL."""

from __future__ import annotations

import pytest
import numpy as np

from qiskit_metal.toolbox_metal.design_dsl import DesignDslError, build_design, build_ir


def _template_yaml(component_body: str) -> str:
    return f"""
schema: qiskit-metal/design-dsl/3
vars:
  pad_w: 500um
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  templates:
    template_pad:
      schema: qiskit-metal/component-template/1
      id: template_pad
      options:
        width: 400um
        height: 90um
        chip: main
        layer: 1
      metadata:
        short_name: TP
      geometry:
        primitives:
          - name: pad
            type: poly.rectangle
            center: [0mm, 0mm]
            size: ["${{options.width}}", "${{options.height}}"]
            chip: "${{options.chip}}"
            layer: "${{options.layer}}"
        pins:
          - name: bus
            points: [[0mm, -6um], [0mm, 6um]]
            width: 12um
            chip: "${{options.chip}}"
  components:
    Q1:
{component_body}
"""


def test_component_template_expands_to_primitives_and_pins():
    ir = build_ir(_template_yaml("""
      type: template_pad
      options:
        width: "${vars.pad_w}"
"""))

    component = ir.components[0]
    assert component.name == "Q1"
    assert component.type == "template_pad"
    assert component.template == "template_pad"
    assert component.inherited == ["template_pad"]
    assert component.options["width"] == "500um"
    assert component.metadata["short_name"] == "TP"
    assert component.metadata["template"]["type"] == "template_pad"
    assert [primitive.name for primitive in component.primitives] == ["pad"]
    assert [pin.name for pin in component.pins] == ["bus"]

    minx, _, maxx, _ = component.primitives[0].geometry.bounds
    assert maxx - minx == pytest.approx(0.5)
    assert ir.geometry["components"]["Q1"]["options"]["width"] == "500um"


def test_component_template_build_design_uses_native_component():
    design = build_design(_template_yaml("""
      type: template_pad
      options:
        width: 450um
"""))

    assert design.components["Q1"].__class__.__name__ == "NativeComponent"
    assert "Q1" in design.components
    assert "bus" in design.components["Q1"].pins
    assert design.metadata["dsl_chain"]["geometry"]["components"]["Q1"][
        "type"] == "template_pad"
    assert design.metadata["dsl_chain"]["geometry"]["components"]["Q1"][
        "options"]["width"] == "450um"


def test_unknown_component_template_type_is_rejected():
    with pytest.raises(DesignDslError, match="Unknown component template type"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: missing_template
""")


def test_unknown_component_template_option_is_rejected():
    with pytest.raises(DesignDslError, match="Unknown component Q1.options"):
        build_ir(_template_yaml("""
      type: template_pad
      options:
        missing: 1
"""))


def test_component_template_extends_parent_defaults_and_geometry():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    template_parent:
      schema: qiskit-metal/component-template/1
      id: template_parent
      options:
        width: 300um
        height: 80um
      geometry:
        pins:
          - {name: bus, points: [[0mm, -5um], [0mm, 5um]], width: 10um}
    template_child:
      schema: qiskit-metal/component-template/1
      id: template_child
      extends: template_parent
      options:
        height: 100um
      geometry:
        primitives:
          - {name: pad, type: poly.rectangle, center: [0mm, 0mm],
             size: ["${options.width}", "${options.height}"]}
  components:
    Q1:
      type: template_child
      options:
        width: 350um
""")

    component = ir.components[0]
    assert component.inherited == ["template_parent", "template_child"]
    assert component.options == {"width": "350um", "height": "100um"}
    assert [pin.name for pin in component.pins] == ["bus"]
    assert [primitive.name for primitive in component.primitives] == ["pad"]


def test_template_expressions_support_units_arithmetic_and_local_context():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars:
  trace: 12um
hamiltonian:
  subsystems:
    Q1: {pad_height: 90um}
circuit:
  Q1: {pad_gap: 30um}
netlist:
  connections:
    - {from: Q1.bus, to: Q2.bus}
geometry:
  design: {class: DesignPlanar}
  templates:
    expression_pad:
      schema: qiskit-metal/component-template/1
      id: expression_pad
      options:
        pad_height: "${hamiltonian.subsystems.Q1.pad_height}"
        pad_gap: "${circuit.Q1.pad_gap}"
        trace_width: "${vars.trace}"
        source_endpoint: "${netlist.connections.0.from}"
      geometry:
        primitives:
          - name: "${component.name}_pad"
            type: poly.rectangle
            center: [0mm, "${(options.pad_height + options.pad_gap) / 2}"]
            size: ["${2 * options.trace_width}", "${options.pad_height / 3}"]
        pins:
          - name: bus
            points: [[0mm, "${-options.trace_width / 2}"],
                     [0mm, "${options.trace_width / 2}"]]
            width: "${options.trace_width}"
  components:
    Q1:
      type: expression_pad
    Q2:
      pins:
        - name: bus
          points: [[0mm, -6um], [0mm, 6um]]
          width: "${vars.trace}"
""")

    component = ir.components[0]
    primitive = component.primitives[0]
    assert primitive.name == "Q1_pad"
    assert primitive.geometry.centroid.y == pytest.approx(0.060)
    minx, miny, maxx, maxy = primitive.geometry.bounds
    assert maxx - minx == pytest.approx(0.024)
    assert maxy - miny == pytest.approx(0.030)
    assert component.pins[0].points[0] == pytest.approx([0.0, -0.006])
    assert component.pins[0].points[1] == pytest.approx([0.0, 0.006])
    assert component.pins[0].width == pytest.approx(0.012)
    assert component.options["source_endpoint"] == "Q1.bus"


def test_template_geometry_operations_feed_primitives():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars:
  trace: 10um
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    op_pad:
      schema: qiskit-metal/component-template/1
      id: op_pad
      options:
        width: 100um
        height: 40um
        yoff: 25um
      geometry:
        operations:
          pad_base:
            op: rectangle
            width: "${options.width}"
            height: "${options.height}"
          pad:
            op: translate
            source: pad_base
            xoff: 15um
            yoff: "${options.yoff}"
          wire:
            op: polyline
            points:
              - [0um, 0um]
              - [50um, 0um]
              - [50um, 20um]
          wire_last:
            op: last_segment
            source: wire
          wire_clearance:
            op: buffer
            source: wire
            distance: "${vars.trace}"
        primitives:
          - name: pad
            type: poly.from_operation
            operation: pad
          - name: wire
            type: path.from_operation
            operation: wire_last
            width: "${vars.trace}"
          - name: wire_clearance
            type: poly.from_operation
            operation: wire_clearance
            subtract: true
  components:
    Q1:
      type: op_pad
""")

    component = ir.components[0]
    primitives = {primitive.name: primitive for primitive in component.primitives}

    pad = primitives["pad"].geometry
    assert pad.centroid.x == pytest.approx(0.015)
    assert pad.centroid.y == pytest.approx(0.025)
    minx, miny, maxx, maxy = pad.bounds
    assert maxx - minx == pytest.approx(0.100)
    assert maxy - miny == pytest.approx(0.040)

    wire = primitives["wire"].geometry
    assert list(wire.coords) == pytest.approx([(0.050, 0.000), (0.050, 0.020)])
    assert primitives["wire"].width == pytest.approx(0.010)
    assert primitives["wire_clearance"].subtract is True
    assert primitives["wire_clearance"].geometry.area > 0


def test_component_geometry_operations_can_be_used_without_template():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      operations:
        tri:
          op: polygon
          points: [[0um, 0um], [100um, 0um], [0um, 100um]]
        placed:
          op: rotate_position
          source: tri
          angle: 90
          pos: [1mm, 2mm]
      primitives:
        - name: tri
          type: poly.from_operation
          operation: placed
""")

    primitive = ir.components[0].primitives[0]
    assert primitive.geometry.area == pytest.approx(0.005)
    minx, miny, maxx, maxy = primitive.geometry.bounds
    assert minx == pytest.approx(0.900)
    assert miny == pytest.approx(2.000)
    assert maxx == pytest.approx(1.000)
    assert maxy == pytest.approx(2.100)


@pytest.mark.parametrize(
    ("bad_center", "message"),
    [
        ('["${missing.value + 1um}", 0mm]', "Unknown expression name"),
        ("[\"${__import__('os')}\", 0mm]", "Unsupported expression syntax"),
    ],
)
def test_template_expression_errors_are_clear(bad_center, message):
    with pytest.raises(DesignDslError, match=message):
        build_ir(f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  templates:
    bad_expr:
      schema: qiskit-metal/component-template/1
      id: bad_expr
      options: {{}}
      geometry:
        primitives:
          - name: pad
            type: poly.rectangle
            center: {bad_center}
            size: [100um, 50um]
  components:
    Q1:
      type: bad_expr
""")


@pytest.mark.parametrize(
    ("operation_body", "message"),
    [
        ("            op: missing_op\n            width: 100um",
         "Unknown geometry operation"),
        ("            op: translate\n            source: missing",
         "Unknown geometry operation reference"),
    ],
)
def test_template_geometry_operation_errors_are_clear(operation_body, message):
    with pytest.raises(DesignDslError, match=message):
        build_ir(f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  templates:
    bad_ops:
      schema: qiskit-metal/component-template/1
      id: bad_ops
      options: {{}}
      geometry:
        operations:
          shape:
{operation_body}
        primitives:
          - name: shape
            type: poly.from_operation
            operation: shape
  components:
    Q1:
      type: bad_ops
""")


def test_normal_segment_pin_mode_uses_operation_last_segment():
    source = """
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      operations:
        wire:
          op: polyline
          points: [[0um, 0um], [100um, 0um]]
      pins:
        - name: readout
          mode: normal_segment
          from_operation: wire
          segment: last
          width: 12um
          gap: 7um
"""

    ir = build_ir(source)
    pin = ir.components[0].pins[0]

    assert pin.input_as_norm is True
    np.testing.assert_allclose(pin.normal_points, [[0.0, 0.0], [0.1, 0.0]])
    np.testing.assert_allclose(pin.points, [[0.1, 0.006], [0.1, -0.006]])

    design = build_design(source)
    exported_pin = design.components["Q1"].pins["readout"]
    np.testing.assert_allclose(exported_pin.middle, [0.1, 0.0])
    np.testing.assert_allclose(exported_pin.normal, [1.0, 0.0])
    np.testing.assert_allclose(exported_pin.points, pin.points)
    assert exported_pin.width == pytest.approx(0.012)
    assert exported_pin.gap == pytest.approx(0.007)


def test_normal_segment_pin_mode_applies_component_transform():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      rotate: 90
      translate: [1mm, 2mm]
      operations:
        wire:
          op: polyline
          points: [[0um, 0um], [100um, 0um]]
      pins:
        - name: readout
          mode: normal_segment
          from_operation: wire
          width: 20um
""")

    pin = ir.components[0].pins[0]
    np.testing.assert_allclose(pin.normal_points, [[1.0, 2.0], [1.0, 2.1]])
    np.testing.assert_allclose(pin.points, [[0.99, 2.1], [1.01, 2.1]])


@pytest.mark.parametrize(
    ("pin_body", "message"),
    [
        ("mode: normal_segment\n          width: 12um",
         "normal_segment requires from_operation"),
        ("mode: normal_segment\n          from_operation: missing\n          "
         "width: 12um",
         "Unknown geometry operation reference"),
        ("mode: tangent_points\n          from_operation: wire\n          "
         "points: [[0um, -6um], [0um, 6um]]\n          width: 12um",
         "tangent_points does not accept"),
    ],
)
def test_pin_mode_errors_are_clear(pin_body, message):
    with pytest.raises(DesignDslError, match=message):
        build_ir(f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  components:
    Q1:
      operations:
        wire:
          op: polyline
          points: [[0um, 0um], [100um, 0um]]
      pins:
        - name: readout
          {pin_body}
""")


def test_template_merge_rules_extend_each_connection_pad_entry():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    pad_parent:
      schema: qiskit-metal/component-template/1
      id: pad_parent
      options:
        connection_pads: {}
        _default_connection_pads:
          cpw_width: 12um
          cpw_gap: 7um
          loc_W: 1
          loc_H: 1
      merge_rules:
        connection_pads:
          each_entry_extends: _default_connection_pads
          remove_from_resolved_options:
            - _default_connection_pads
      geometry:
        primitives: []
    pad_child:
      schema: qiskit-metal/component-template/1
      id: pad_child
      extends: pad_parent
      options:
        _default_connection_pads:
          cpw_gap: 9um
  components:
    Q1:
      type: pad_child
      options:
        connection_pads:
          readout:
            loc_W: -1
          drive:
            cpw_width: 20um
""")

    options = ir.components[0].options
    assert "_default_connection_pads" not in options
    assert options["connection_pads"]["readout"] == {
        "cpw_width": "12um",
        "cpw_gap": "9um",
        "loc_W": -1,
        "loc_H": 1,
    }
    assert options["connection_pads"]["drive"]["cpw_width"] == "20um"
    assert options["connection_pads"]["drive"]["cpw_gap"] == "9um"


def test_template_merge_rules_reject_unknown_connection_pad_key():
    with pytest.raises(DesignDslError,
                       match="Unknown component Q1.options.connection_pads.readout"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    pad_parent:
      schema: qiskit-metal/component-template/1
      id: pad_parent
      options:
        connection_pads: {}
        _default_connection_pads:
          cpw_width: 12um
      merge_rules:
        connection_pads:
          each_entry_extends: _default_connection_pads
      geometry:
        primitives: []
  components:
    Q1:
      type: pad_parent
      options:
        connection_pads:
          readout:
            missing: true
""")


@pytest.mark.parametrize("bad_metadata", ["[]", "''", "false"])
def test_typed_component_rejects_non_mapping_metadata(bad_metadata):
    with pytest.raises(DesignDslError, match="metadata must be a mapping"):
        build_ir(f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  templates:
    template_pad:
      schema: qiskit-metal/component-template/1
      id: template_pad
      options: {{}}
      geometry:
        primitives: []
  components:
    Q1:
      type: template_pad
      metadata: {bad_metadata}
""")


def test_template_generators_are_not_silently_ignored_before_support_lands():
    with pytest.raises(DesignDslError, match="geometry.generators"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    generator_template:
      schema: qiskit-metal/component-template/1
      id: generator_template
      options: {}
      geometry:
        generators:
          connection_pads:
            for_each: options.connection_pads
  components:
    Q1:
      type: generator_template
""")
