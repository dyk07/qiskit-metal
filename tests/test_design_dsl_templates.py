# -*- coding: utf-8 -*-
"""Tests for YAML-native component templates in the v3 design DSL."""

from __future__ import annotations

import pytest

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
