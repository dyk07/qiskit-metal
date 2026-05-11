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


def test_template_expression_runtime_errors_use_design_dsl_error():
    with pytest.raises(DesignDslError, match=r"Expression \$\{1 / 0\}"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    bad_expr:
      schema: qiskit-metal/component-template/1
      id: bad_expr
      options: {}
      geometry:
        primitives:
          - name: pad
            type: poly.rectangle
            center: ["${1 / 0}", 0mm]
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
"""

    ir = build_ir(source)

    pin = ir.components[0].pins[0]
    np.testing.assert_allclose(pin.normal_points, [[1.0, 2.0], [1.0, 2.1]])
    np.testing.assert_allclose(pin.points, [[0.99, 2.1], [1.01, 2.1]])

    design = build_design(source)
    exported_pin = design.components["Q1"].pins["readout"]
    np.testing.assert_allclose(exported_pin.points, pin.points)


def test_normal_segment_pin_mode_matches_export_for_non_right_angle_transform():
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
      rotate: 45
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
"""

    ir = build_ir(source)
    pin = ir.components[0].pins[0]
    derived_pin = ir.derived["circuit"]["geometry"]["Q1"]["pins"]["readout"]
    design = build_design(source)
    exported_pin = design.components["Q1"].pins["readout"]

    np.testing.assert_allclose(pin.normal_points,
                               [[1.0, 2.0],
                                [1.0707106781186548, 2.0707106781186546]])
    np.testing.assert_allclose(pin.points, exported_pin.points)
    np.testing.assert_allclose(derived_pin["points"], exported_pin.points)
    np.testing.assert_allclose(exported_pin.middle, pin.normal_points[-1])
    np.testing.assert_allclose(exported_pin.normal,
                               [0.70710678, 0.70710678])


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


@pytest.mark.parametrize(
    ("geometry_body", "message"),
    [
        ("        operations: []", "geometry.operations must be a mapping"),
        ("        operations: false", "geometry.operations must be a mapping"),
        ("        transform: []", "geometry.transform must be a mapping"),
    ],
)
def test_template_rejects_malformed_geometry_maps(geometry_body, message):
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
    bad_template:
      schema: qiskit-metal/component-template/1
      id: bad_template
      options: {{}}
      geometry:
{geometry_body}
        primitives: []
  components:
    Q1:
      type: bad_template
""")


def test_typed_component_rejects_malformed_instance_operations():
    with pytest.raises(DesignDslError, match="Q1.operations must be a mapping"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    template_pad:
      schema: qiskit-metal/component-template/1
      id: template_pad
      options: {}
      geometry:
        primitives: []
  components:
    Q1:
      type: template_pad
      operations: []
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


def test_template_generators_expand_primitives_pins_and_netlist():
    source = """
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist:
  connections:
    - {from: Q1.left, to: Q2.bus}
geometry:
  design: {class: DesignPlanar}
  templates:
    generated_ports:
      schema: qiskit-metal/component-template/1
      id: generated_ports
      options:
        connection_pads: {}
        _default_connection_pads:
          x: 100um
          width: 12um
          loc: 1
      merge_rules:
        connection_pads:
          each_entry_extends: _default_connection_pads
          remove_from_resolved_options:
            - _default_connection_pads
      geometry:
        generators:
          connection_pads:
            for_each: "${options.connection_pads}"
            as: pad
            operations:
              wire:
                op: polyline
                points:
                  - ["${pad.value.loc * pad.value.x}", 0um]
                  - ["${pad.value.loc * (pad.value.x + 100um)}", 0um]
            primitives:
              - name: "${pad.key}_wire"
                type: path.from_operation
                operation: wire
                width: "${pad.value.width}"
            pins:
              - name: "${pad.key}"
                mode: normal_segment
                from_operation: wire
                width: "${pad.value.width}"
  components:
    Q1:
      type: generated_ports
      options:
        connection_pads:
          left:
            loc: -1
          right:
            loc: 1
    Q2:
      pins:
        - name: bus
          points: [[1mm, -6um], [1mm, 6um]]
          width: 12um
"""

    ir = build_ir(source)
    component = ir.components[0]
    assert {primitive.name for primitive in component.primitives} == {
        "left_wire",
        "right_wire",
    }
    assert {pin.name for pin in component.pins} == {"left", "right"}

    left_wire = next(primitive for primitive in component.primitives
                     if primitive.name == "left_wire")
    assert list(left_wire.geometry.coords) == pytest.approx([(-0.1, 0.0),
                                                             (-0.2, 0.0)])
    left_pin = next(pin for pin in component.pins if pin.name == "left")
    np.testing.assert_allclose(left_pin.normal_points, [[-0.1, 0.0],
                                                        [-0.2, 0.0]])

    design = build_design(source)
    assert "left" in design.components["Q1"].pins
    assert len(design.net_info) == 2


def test_builtin_qcomponent_template_supplies_transform_and_runtime_options():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    placed_rect:
      schema: qiskit-metal/component-template/1
      id: placed_rect
      extends: qcomponent
      options:
        width: 100um
        height: 50um
      geometry:
        primitives:
          - name: pad
            type: poly.rectangle
            center: [0um, 0um]
            size: ["${options.width}", "${options.height}"]
            chip: "${options.chip}"
            layer: "${options.layer}"
        pins:
          - name: bus
            points: [[0um, -5um], [0um, 5um]]
            width: 10um
            chip: "${options.chip}"
  components:
    Q1:
      type: placed_rect
      options:
        pos_x: 1mm
        pos_y: 2mm
        orientation: 90
        chip: main
        layer: 3
""")

    component = ir.components[0]
    assert component.inherited == ["qcomponent", "placed_rect"]
    assert component.options["pos_x"] == "1mm"
    assert component.options["pos_y"] == "2mm"
    assert component.options["orientation"] == 90
    assert component.options["chip"] == "main"
    assert component.options["layer"] == 3

    primitive = component.primitives[0]
    assert primitive.chip == "main"
    assert primitive.layer == 3
    assert primitive.geometry.centroid.x == pytest.approx(1.0)
    assert primitive.geometry.centroid.y == pytest.approx(2.0)
    minx, miny, maxx, maxy = primitive.geometry.bounds
    assert maxx - minx == pytest.approx(0.050)
    assert maxy - miny == pytest.approx(0.100)

    pin = component.pins[0]
    assert pin.chip == "main"
    np.testing.assert_allclose(pin.points, [[1.005, 2.0], [0.995, 2.0]])


def test_builtin_base_qubit_template_inherits_qcomponent_and_connection_pads():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    qubit_stub:
      schema: qiskit-metal/component-template/1
      id: qubit_stub
      extends: base_qubit
      options:
        _default_connection_pads:
          cpw_width: 12um
          cpw_gap: 7um
          loc_W: 1
          loc_H: 1
      geometry:
        primitives:
          - name: marker
            type: poly.rectangle
            center: [0um, 0um]
            size: [100um, 50um]
            chip: "${options.chip}"
            layer: "${options.layer}"
  components:
    Q1:
      type: qubit_stub
      options:
        pos_x: 500um
        connection_pads:
          readout:
            loc_W: -1
          drive:
            cpw_gap: 9um
""")

    component = ir.components[0]
    assert component.inherited == ["qcomponent", "base_qubit", "qubit_stub"]
    assert component.metadata["short_name"] == "Q"
    assert "_default_connection_pads" not in component.options
    assert component.options["connection_pads"]["readout"] == {
        "cpw_width": "12um",
        "cpw_gap": "7um",
        "loc_W": -1,
        "loc_H": 1,
    }
    assert component.options["connection_pads"]["drive"]["cpw_width"] == "12um"
    assert component.options["connection_pads"]["drive"]["cpw_gap"] == "9um"
    assert component.primitives[0].geometry.centroid.x == pytest.approx(0.5)


def test_builtin_transmon_pocket_template_generates_static_pocket_geometry():
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
      type: transmon_pocket
      options:
        pos_x: 1mm
        pos_y: 2mm
        orientation: 90
        layer: 4
""")

    component = ir.components[0]
    assert component.inherited == [
        "qcomponent",
        "base_qubit",
        "transmon_pocket",
    ]
    assert component.metadata["short_name"] == "Pocket"
    assert component.metadata["qgeometry_tables"] == ["poly", "path", "junction"]
    assert "_default_connection_pads" not in component.options
    assert component.options["connection_pads"] == {}

    primitives = {primitive.name: primitive for primitive in component.primitives}
    assert set(primitives) == {"pad_top", "pad_bot", "rect_pk", "rect_jj"}
    assert primitives["pad_top"].kind == "poly"
    assert primitives["pad_bot"].kind == "poly"
    assert primitives["rect_pk"].subtract is True
    assert primitives["rect_jj"].kind == "junction"
    assert primitives["rect_jj"].width == pytest.approx(0.020)
    assert all(primitive.layer == 4 for primitive in primitives.values())

    assert primitives["pad_top"].geometry.centroid.x == pytest.approx(0.940)
    assert primitives["pad_top"].geometry.centroid.y == pytest.approx(2.0)
    assert primitives["pad_bot"].geometry.centroid.x == pytest.approx(1.060)
    assert primitives["pad_bot"].geometry.centroid.y == pytest.approx(2.0)
    minx, miny, maxx, maxy = primitives["rect_pk"].geometry.bounds
    assert maxx - minx == pytest.approx(0.650)
    assert maxy - miny == pytest.approx(0.650)
    assert primitives["rect_jj"].geometry.length == pytest.approx(0.030)


def test_builtin_transmon_pocket_exports_static_rows_without_qlibrary_construction(
        monkeypatch):
    from qiskit_metal.qlibrary.qubits.transmon_pocket import TransmonPocket

    def fail_init(*args, **kwargs):
        raise AssertionError("qlibrary TransmonPocket must not be constructed")

    monkeypatch.setattr(TransmonPocket, "__init__", fail_init)

    design = build_design("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
""")

    component = design.components["Q1"]
    assert component.__class__.__name__ == "NativeComponent"
    poly_rows = design.qgeometry.tables["poly"]
    junction_rows = design.qgeometry.tables["junction"]
    assert set(poly_rows["name"]) == {"pad_top", "pad_bot", "rect_pk"}
    assert set(junction_rows["name"]) == {"rect_jj"}
    rect_pk = poly_rows[poly_rows["name"] == "rect_pk"].iloc[0]
    rect_jj = junction_rows[junction_rows["name"] == "rect_jj"].iloc[0]
    assert bool(rect_pk["subtract"]) is True
    assert rect_jj["width"] == pytest.approx(0.020)
    assert component.metadata["template"]["type"] == "transmon_pocket"


def test_builtin_transmon_pocket_generates_connection_pad_geometry_and_pin():
    source = """
schema: qiskit-metal/design-dsl/3
vars:
  cpw_width: 12um
  cpw_gap: 7um
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        layer: 2
        connection_pads:
          readout: {}
"""

    ir = build_ir(source)
    component = ir.components[0]
    primitives = {primitive.name: primitive for primitive in component.primitives}
    assert set(primitives) == {
        "pad_top",
        "pad_bot",
        "rect_pk",
        "rect_jj",
        "readout_connector_pad",
        "readout_wire",
        "readout_wire_sub",
    }
    assert primitives["readout_connector_pad"].kind == "poly"
    assert primitives["readout_wire"].kind == "path"
    assert primitives["readout_wire"].width == pytest.approx(0.012)
    assert primitives["readout_wire_sub"].kind == "path"
    assert primitives["readout_wire_sub"].width == pytest.approx(0.026)
    assert primitives["readout_wire_sub"].subtract is True
    assert all(primitive.layer == 2 for primitive in primitives.values())

    readout_wire = primitives["readout_wire"].geometry
    np.testing.assert_allclose(list(readout_wire.coords), [
        (0.2275, 0.131),
        (0.2525, 0.131),
        (0.32, 0.196),
        (0.425, 0.196),
    ])

    pin = component.pins[0]
    assert pin.name == "readout"
    assert pin.width == pytest.approx(0.012)
    assert pin.gap == pytest.approx(0.0072)
    np.testing.assert_allclose(pin.normal_points, [[0.32, 0.196],
                                                   [0.425, 0.196]])

    design = build_design(source)
    exported_pin = design.components["Q1"].pins["readout"]
    np.testing.assert_allclose(exported_pin.points, pin.points)
    assert exported_pin.gap == pytest.approx(0.0072)
    assert set(design.qgeometry.tables["poly"]["name"]) == {
        "pad_top",
        "pad_bot",
        "rect_pk",
        "readout_connector_pad",
    }
    assert set(design.qgeometry.tables["path"]["name"]) == {
        "readout_wire",
        "readout_wire_sub",
    }


def test_builtin_transmon_pocket_default_connection_pad_uses_design_variables():
    source = """
schema: qiskit-metal/design-dsl/3
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        connection_pads:
          readout: {}
"""

    ir = build_ir(source)
    component = ir.components[0]
    primitives = {primitive.name: primitive for primitive in component.primitives}
    assert primitives["readout_wire"].width == pytest.approx(0.010)
    assert primitives["readout_wire_sub"].width == pytest.approx(0.022)

    pin = component.pins[0]
    assert pin.name == "readout"
    assert pin.width == pytest.approx(0.010)
    assert pin.gap == pytest.approx(0.006)

    design = build_design(source)
    exported_pin = design.components["Q1"].pins["readout"]
    assert exported_pin.width == pytest.approx(0.010)
    assert exported_pin.gap == pytest.approx(0.006)


@pytest.mark.parametrize(
    ("option_line", "message"),
    [
        ("orientation: nope", r"transform\.rotate"),
        ("orientation: true", r"transform\.rotate"),
        ("layer: true", r"primitive Q1\.pad_top\.layer"),
    ],
)
def test_builtin_template_invalid_numeric_options_raise_design_dsl_error(
        option_line, message):
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
      type: transmon_pocket
      options:
        {option_line}
""")


def test_builtin_transmon_pocket_connection_pad_overrides_and_netlist():
    source = """
schema: qiskit-metal/design-dsl/3
vars:
  cpw_width: 12um
  cpw_gap: 7um
hamiltonian: {}
circuit: {}
netlist:
  connections:
    - {from: Q1.readout, to: Q2.readout}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: -1mm
        connection_pads:
          readout:
            loc_W: 1
            loc_H: 1
    Q2:
      type: transmon_pocket
      options:
        pos_x: 1mm
        connection_pads:
          readout:
            loc_W: -1
            loc_H: 1
            cpw_width: 16um
            cpw_gap: 8um
"""

    ir = build_ir(source)
    q2 = next(component for component in ir.components if component.name == "Q2")
    q2_primitives = {primitive.name: primitive for primitive in q2.primitives}
    assert q2.options["connection_pads"]["readout"]["cpw_width"] == "16um"
    assert q2.options["connection_pads"]["readout"]["cpw_gap"] == "8um"
    assert q2_primitives["readout_wire"].width == pytest.approx(0.016)
    assert q2_primitives["readout_wire_sub"].width == pytest.approx(0.032)

    design = build_design(source)
    assert "readout" in design.components["Q1"].pins
    assert "readout" in design.components["Q2"].pins
    assert len(design.net_info) == 2
    assert int(design.components["Q1"].pins["readout"].net_id) == int(
        design.components["Q2"].pins["readout"].net_id)


def test_builtin_transmon_pocket_connection_pad_uses_component_transform_once():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars:
  cpw_width: 12um
  cpw_gap: 7um
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: 1mm
        pos_y: 2mm
        orientation: 90
        connection_pads:
          readout: {}
""")

    component = ir.components[0]
    primitives = {primitive.name: primitive for primitive in component.primitives}
    wire = primitives["readout_wire"].geometry
    np.testing.assert_allclose(list(wire.coords), [
        (0.869, 2.2275),
        (0.869, 2.2525),
        (0.804, 2.32),
        (0.804, 2.425),
    ])
    pin = component.pins[0]
    np.testing.assert_allclose(pin.normal_points, [[0.804, 2.32],
                                                   [0.804, 2.425]])


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


def test_template_generators_reject_invalid_iterator():
    with pytest.raises(DesignDslError,
                       match="for_each is invalid"):
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
      options:
        connection_pads: {}
      geometry:
        generators:
          connection_pads:
            for_each: missing.connection_pads
  components:
    Q1:
      type: generator_template
""")


def test_component_template_file_lookup_from_design_directory(tmp_path):
    template_file = tmp_path / "local_pad.yaml"
    template_file.write_text("""
schema: qiskit-metal/component-template/1
id: local_pad.yaml
options:
  width: 300um
  height: 80um
geometry:
  primitives:
    - name: pad
      type: poly.rectangle
      center: [0mm, 0mm]
      size: ["${options.width}", "${options.height}"]
  pins:
    - name: bus
      points: [[0mm, -5um], [0mm, 5um]]
      width: 10um
""",
                             encoding="utf-8")

    design_file = tmp_path / "design.yaml"
    design_file.write_text("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: local_pad.yaml
      options:
        width: 450um
""",
                           encoding="utf-8")

    ir = build_ir(design_file)

    component = ir.components[0]
    assert component.type == "local_pad.yaml"
    assert component.template == "local_pad.yaml"
    assert component.options["width"] == "450um"
    assert [primitive.name for primitive in component.primitives] == ["pad"]
    assert [pin.name for pin in component.pins] == ["bus"]
    minx, _, maxx, _ = component.primitives[0].geometry.bounds
    assert maxx - minx == pytest.approx(0.450)


def test_component_template_file_id_mismatch_is_rejected(tmp_path):
    template_file = tmp_path / "local_pad.yaml"
    template_file.write_text("""
schema: qiskit-metal/component-template/1
id: wrong_id
options: {}
geometry: {}
""",
                             encoding="utf-8")
    design_file = tmp_path / "design.yaml"
    design_file.write_text("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: local_pad.yaml
""",
                           encoding="utf-8")

    with pytest.raises(DesignDslError, match="declares id 'wrong_id'"):
        build_ir(design_file)


def test_component_template_file_duplicate_key_is_rejected(tmp_path):
    template_file = tmp_path / "local_pad.yaml"
    template_file.write_text("""
schema: qiskit-metal/component-template/1
id: local_pad.yaml
options: {}
options: {}
geometry: {}
""",
                             encoding="utf-8")
    design_file = tmp_path / "design.yaml"
    design_file.write_text("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: local_pad.yaml
""",
                           encoding="utf-8")

    with pytest.raises(DesignDslError, match="Duplicate YAML mapping key"):
        build_ir(design_file)
