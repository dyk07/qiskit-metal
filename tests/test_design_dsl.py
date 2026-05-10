# -*- coding: utf-8 -*-
"""Tests for the native v3 YAML design DSL."""

from __future__ import annotations

from pathlib import Path

import pytest

from qiskit_metal.toolbox_metal.design_dsl import (
    CURRENT_SCHEMA,
    DesignDslError,
    build_design,
    build_ir,
)


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dsl" / (
    "chain_2q_native.metal.yaml")


def _minimal_yaml(extra_geometry: str = "") -> str:
    return f"""
schema: {CURRENT_SCHEMA}
vars:
  qx: 1.0mm
  pad_w: 400um
  trace_w: 12um
  trace_gap: 7um
hamiltonian:
  subsystems:
    Q1: {{EJ: 18GHz}}
circuit:
  Q1: {{pad_width: "${{pad_w}}"}}
netlist:
  connections:
    - {{from: Q1.bus, to: Q2.bus}}
geometry:
  design:
    class: DesignPlanar
    chip: {{size: 4mm x 4mm}}
  components:
    Q1:
      primitives:
        - {{name: pad, type: poly.rectangle, center: [0mm, 0mm],
           size: ["${{circuit.Q1.pad_width}}", 90um]}}
      pins:
        - {{name: bus, points: [[0.2mm, -6um], [0.2mm, 6um]],
           width: "${{trace_w}}", gap: "${{trace_gap}}"}}
    Q2:
      primitives:
        - {{name: trace, type: path.line, points: [[0mm, 0mm], [1mm, 0mm]],
           width: "${{trace_w}}"}}
      pins:
        - {{name: bus, points: [[-0.2mm, -6um], [-0.2mm, 6um]],
           width: "${{trace_w}}", gap: "${{trace_gap}}"}}
{extra_geometry}
"""


def test_build_ir_resolves_circuit_to_geometry():
    ir = build_ir(EXAMPLE)

    assert ir.schema == CURRENT_SCHEMA
    q1 = next(component for component in ir.components if component.name == "Q1")
    pad = next(primitive for primitive in q1.primitives
               if primitive.name == "pad_left")

    minx, _, maxx, _ = pad.geometry.bounds
    assert pytest.approx(maxx - minx) == 0.420
    assert ir.hamiltonian["subsystems"]["Q1"]["C"] == "65fF"


def test_build_design_writes_qgeometry_pins_and_netlist():
    design = build_design(EXAMPLE)

    assert len(design.qgeometry.tables["poly"]) >= 6
    assert len(design.qgeometry.tables["path"]) == 2
    assert len(design.qgeometry.tables["junction"]) == 2
    assert "bus" in design.components["Q1"].pins
    assert len(design.net_info) == 4


def test_derived_contains_bounds_lengths_pins_and_connections():
    ir = build_ir(EXAMPLE)
    derived = ir.derived

    bus_data = derived["circuit"]["geometry"]["bus"]
    assert bus_data["primitives"]["center_trace"]["length"] == pytest.approx(2.4)
    assert bus_data["pins"]["start"]["middle"][0] == pytest.approx(-1.2)
    assert derived["netlist"]["connections"][0]["from"] == {
        "component": "Q1",
        "pin": "bus",
    }


def test_overrides_recompute_geometry():
    ir = build_ir(EXAMPLE,
                  overrides={"circuit": {
                      "Q1": {
                          "pad_width": "500um"
                      }
                  }})
    q1 = next(component for component in ir.components if component.name == "Q1")
    pad = next(primitive for primitive in q1.primitives
               if primitive.name == "pad_left")
    minx, _, maxx, _ = pad.geometry.bounds

    assert pytest.approx(maxx - minx) == 0.500


def test_inline_minimal_yaml_builds():
    design = build_design(_minimal_yaml())

    assert set(design.components.keys()) >= {"Q1", "Q2"}
    assert len(design.qgeometry.tables["poly"]) == 1
    assert len(design.qgeometry.tables["path"]) == 1
    assert len(design.net_info) == 2


def test_include_template_loop_and_interpolation(tmp_path):
    templates = tmp_path / "templates.yaml"
    templates.write_text("""
rect_template:
  primitives:
    - {name: pad, type: poly.rectangle, center: [0mm, 0mm],
       size: ["${vars.pad_w}", 90um]}
  pins:
    - {name: bus, points: [[0.2mm, -6um], [0.2mm, 6um]], width: 12um}
""",
                         encoding="utf-8")

    design_file = tmp_path / "design.yaml"
    design_file.write_text(f"""
schema: {CURRENT_SCHEMA}
vars: {{pad_w: 410um}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  templates:
    $include: templates.yaml
  components:
    - $for:
        - {{name: Q1, x: -1mm}}
        - {{name: Q2, x: 1mm}}
      $extend: rect_template
      name: ${{name}}
      translate: ["${{x}}", 0mm]
""",
                           encoding="utf-8")

    ir = build_ir(design_file)

    assert [component.name for component in ir.components] == ["Q1", "Q2"]
    assert ir.components[0].primitives[0].geometry.centroid.x == pytest.approx(-1.0)
    assert ir.components[1].primitives[0].geometry.centroid.x == pytest.approx(1.0)


def test_polygon_and_junction_primitives():
    ir = build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    island:
      primitives:
        - {name: tri, type: poly.polygon,
           points: [[0mm, 0mm], [1mm, 0mm], [0mm, 1mm]]}
        - {name: jj, type: junction.line,
           points: [[0mm, 0mm], [0mm, 100um]], width: 10um}
""")

    comp = ir.components[0]
    assert comp.primitives[0].geometry.area == pytest.approx(0.5)
    assert comp.primitives[1].geometry.length == pytest.approx(0.1)


@pytest.mark.parametrize("bad_yaml", [
    """
schema: qiskit-metal/design-dsl/2
geometry: {design: {class: DesignPlanar}, components: {}}
""",
    """
schema: qiskit-metal/design-dsl/3
geometry:
  design: {class: DesignPlanar}
  components:
    Q1: {class: TransmonPocket}
""",
    """
schema: qiskit-metal/design-dsl/3
geometry:
  design: {class: DesignPlanar}
  routes: []
  components: {}
""",
])
def test_rejects_legacy_or_qlibrary_shapes(bad_yaml):
    with pytest.raises(DesignDslError):
        build_ir(bad_yaml)


def test_export_errors_for_missing_netlist_pin():
    with pytest.raises(DesignDslError, match="unknown pin"):
        build_design(_minimal_yaml().replace("Q2.bus", "Q2.nope"))
