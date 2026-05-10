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
    clear_user_registry,
    register_design,
)
from qiskit_metal.designs.design_planar import DesignPlanar


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dsl" / (
    "chain_2q_native.metal.yaml")


class RendererDefaultDesign(DesignPlanar):
    """Design test double with renderer defaults but no renderer startup."""

    def __init__(self, *args, **kwargs):
        kwargs["enable_renderers"] = False
        super().__init__(*args, **kwargs)
        self.renderer_defaults_by_table["junction"] = {
            "dummy": {
                "inductance": "10nH",
            },
        }


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
    assert design.components["Q1"].pins["bus"].width == pytest.approx(0.012)
    assert len(design.net_info) == 4


def test_design_multiplanar_short_name_resolves_to_actual_class():
    design = build_design(_minimal_yaml().replace("class: DesignPlanar",
                                                  "class: DesignMultiPlanar"))

    assert design.__class__.__name__ == "MultiPlanar"


@pytest.mark.parametrize("field", ["metadata", "variables", "chip"])
@pytest.mark.parametrize("bad_value", ["[]", "''", "false"])
def test_rejects_non_mapping_design_fields(field, bad_value):
    source = f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design:
    class: DesignPlanar
    {field}: {bad_value}
  components:
    Q1:
      pins:
        - {{name: bus, points: [[0mm, -6um], [0mm, 6um]], width: 12um}}
"""

    with pytest.raises(DesignDslError, match=f"{field} must be a mapping"):
        build_design(source)


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


def test_include_cycle_is_rejected(tmp_path):
    a_file = tmp_path / "a.yaml"
    b_file = tmp_path / "b.yaml"
    a_file.write_text("$include: b.yaml\n", encoding="utf-8")
    b_file.write_text("$include: a.yaml\n", encoding="utf-8")

    with pytest.raises(DesignDslError, match="include cycle"):
        build_ir(a_file)


def test_duplicate_yaml_mapping_key_is_rejected():
    with pytest.raises(DesignDslError, match="Duplicate YAML mapping key"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars:
  qx: 1mm
  qx: 2mm
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components: {}
""")


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


def test_pin_width_must_match_pin_points():
    with pytest.raises(DesignDslError, match="width .* does not match"):
        build_ir(_minimal_yaml().replace("width: \"${trace_w}\"", "width: 20um", 1))


def test_build_ir_rejects_bad_netlist_endpoint():
    with pytest.raises(DesignDslError, match="unknown pin Q2.nope"):
        build_ir(_minimal_yaml().replace("Q2.bus", "Q2.nope"))


def test_rejects_root_typo_netlsit():
    source = _minimal_yaml().replace("netlist:", "netlsit:", 1)

    with pytest.raises(DesignDslError, match="Unknown root key"):
        build_ir(source)


def test_rejects_geometry_design_typo_clas():
    source = _minimal_yaml().replace("class: DesignPlanar", "clas: DesignPlanar")

    with pytest.raises(DesignDslError, match="Unknown geometry.design key"):
        build_ir(source)


def test_rejects_primitive_typo_widht():
    source = _minimal_yaml().replace('width: "${trace_w}"}', 'widht: "${trace_w}"}',
                                     1)

    with pytest.raises(DesignDslError, match="Unknown primitive Q2.trace key"):
        build_ir(source)


def test_rejects_pin_typo_gpa():
    source = _minimal_yaml().replace('gap: "${trace_gap}"',
                                     'gap: "${trace_gap}", gpa: 7um', 1)

    with pytest.raises(DesignDslError, match="Unknown pin Q1.bus key"):
        build_ir(source)


def test_rejects_netlist_connections_typo():
    source = _minimal_yaml().replace("connections:", "connetions:", 1)

    with pytest.raises(DesignDslError, match="Unknown netlist key"):
        build_ir(source)


def test_rejects_extra_netlist_connection_key():
    source = _minimal_yaml().replace("{from: Q1.bus, to: Q2.bus}",
                                     "{from: Q1.bus, to: Q2.bus, role: drive}",
                                     1)

    with pytest.raises(DesignDslError,
                       match=r"Unknown netlist\.connections\[0\] key"):
        build_ir(source)


def test_rejects_chip_typo_szie():
    source = _minimal_yaml().replace("chip: {size: 4mm x 4mm}",
                                     "chip: {szie: 4mm x 4mm}", 1)

    with pytest.raises(DesignDslError,
                       match="Unknown geometry.design.chip key"):
        build_ir(source)


def test_rejects_component_mapping_key_name_mismatch():
    source = _minimal_yaml().replace("Q1:\n      primitives:",
                                     "Q1:\n      name: Q2\n      primitives:",
                                     1)

    with pytest.raises(DesignDslError, match="does not match explicit name"):
        build_ir(source)


def test_omitted_pin_gap_is_resolved_in_ir_and_export():
    source = _minimal_yaml().replace(', gap: "${trace_gap}"', "", 1)

    ir = build_ir(source)
    q1 = next(component for component in ir.components if component.name == "Q1")
    bus_pin = next(pin for pin in q1.pins if pin.name == "bus")
    design = build_design(source)

    assert bus_pin.gap == pytest.approx(0.012 * 0.6)
    assert ir.derived["circuit"]["geometry"]["Q1"]["pins"]["bus"][
        "gap"] == pytest.approx(bus_pin.gap)
    assert design.metadata["dsl_chain"]["derived"]["circuit"]["geometry"]["Q1"][
        "pins"]["bus"]["gap"] == pytest.approx(bus_pin.gap)
    assert design.components["Q1"].pins["bus"].gap == pytest.approx(bus_pin.gap)


@pytest.mark.parametrize("bad_netlist", [
    "netlist:\n  - {from: Q1.bus, to: Q2.bus}",
    "netlist: []",
    "netlist: ''",
    "netlist: false",
])
def test_build_ir_rejects_non_mapping_netlist(bad_netlist):
    with pytest.raises(DesignDslError, match="netlist must be a mapping"):
        build_ir(_minimal_yaml().replace(
            "netlist:\n  connections:\n    - {from: Q1.bus, to: Q2.bus}",
            bad_netlist))


def test_build_ir_rejects_non_list_connections():
    with pytest.raises(DesignDslError, match="connections must be a list"):
        build_ir(_minimal_yaml().replace(
            "connections:\n    - {from: Q1.bus, to: Q2.bus}",
            "connections: {}"))


@pytest.mark.parametrize("replacement, message", [
    ("- {from: Q1.bus, to: Q1.bus}", "self-connection"),
    ("- {from: Q1.bus, to: Q2.bus}\n    - {from: Q1.bus, to: Q2.bus}",
     "endpoint reused"),
])
def test_build_ir_rejects_invalid_netlist_pin_use(replacement, message):
    source = _minimal_yaml().replace(
        "- {from: Q1.bus, to: Q2.bus}",
        replacement,
    )
    with pytest.raises(DesignDslError, match=message):
        build_ir(source)


@pytest.mark.parametrize("replacement, message", [
    ("points: [[0.2mm, -6um], [0.2mm, 0um], [0.2mm, 6um]]",
     "requires exactly two points"),
])
def test_rejects_invalid_pin(replacement, message):
    source = _minimal_yaml().replace(
        "points: [[0.2mm, -6um], [0.2mm, 6um]]", replacement, 1)
    with pytest.raises(DesignDslError, match=message):
        build_ir(source)


def test_rejects_missing_path_width():
    with pytest.raises(DesignDslError, match="requires width"):
        build_ir("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    bus:
      primitives:
        - {name: trace, type: path.line, points: [[0mm, 0mm], [1mm, 0mm]]}
""")


def test_rejects_missing_junction_width():
    with pytest.raises(DesignDslError, match="requires width"):
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
      primitives:
        - {name: jj, type: junction.line, points: [[0mm, 0mm], [0mm, 100um]]}
""")


@pytest.mark.parametrize("field", ["primitives", "pins"])
def test_rejects_non_list_component_child_fields(field):
    yaml_text = f"""
schema: qiskit-metal/design-dsl/3
vars: {{}}
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  components:
    Q1:
      {field}: {{}}
"""
    with pytest.raises(DesignDslError, match=f"{field} must be a list"):
        build_ir(yaml_text)


@pytest.mark.parametrize("bad_transform", [
    "traslate: [1mm, 0mm]",
    "transform: {scale: 2}",
])
def test_rejects_unknown_transform_keys(bad_transform):
    with pytest.raises(DesignDslError, match="Unknown .*key"):
        build_ir(_minimal_yaml().replace("primitives:", f"{bad_transform}\n      primitives:", 1))


@pytest.mark.parametrize("replacement", [
    'name: pad, transform: {scale: 2}, type: poly.rectangle',
    'name: bus, transform: {scale: 2}, points',
])
def test_rejects_unknown_primitive_or_pin_transform_keys(replacement):
    if "type:" in replacement:
        source = _minimal_yaml().replace("name: pad, type: poly.rectangle",
                                         replacement)
    else:
        source = _minimal_yaml().replace("name: bus, points", replacement)
    with pytest.raises(DesignDslError, match="Unknown transform key"):
        build_ir(source)


@pytest.mark.parametrize("bad_transforms", [
    "transforms: []",
    "transforms: false",
])
def test_rejects_non_mapping_geometry_transforms(bad_transforms):
    source = _minimal_yaml().replace("components:", f"{bad_transforms}\n  components:")
    with pytest.raises(DesignDslError, match="geometry.transforms must be a mapping"):
        build_ir(source)


def test_rejects_transform_for_unknown_component():
    source = _minimal_yaml().replace(
        "components:",
        "transforms:\n    Missing: {translate: [1mm, 0mm]}\n  components:",
    )
    with pytest.raises(DesignDslError,
                       match="transforms references unknown component"):
        build_ir(source)


def test_rejects_unknown_geometry_key_typo():
    source = _minimal_yaml().replace("components:",
                                     "trasforms: {}\n  components:")
    with pytest.raises(DesignDslError, match="Unknown geometry key"):
        build_ir(source)


@pytest.mark.parametrize("replacement, message", [
    ('size: ["${circuit.Q1.pad_width}", 90um], subtract: tru',
     "Q1.pad.subtract"),
    ('size: ["${circuit.Q1.pad_width}", 90um], helper: maybe',
     "Q1.pad.helper"),
])
def test_rejects_invalid_primitive_bool_strings(replacement, message):
    source = _minimal_yaml().replace('size: ["${circuit.Q1.pad_width}", 90um]',
                                     replacement, 1)

    with pytest.raises(DesignDslError, match=message):
        build_ir(source)


def test_rejects_invalid_design_bool_string():
    source = _minimal_yaml().replace(
        "class: DesignPlanar",
        "class: DesignPlanar\n    overwrite_enabled: perhaps",
    )

    with pytest.raises(DesignDslError,
                       match="geometry.design.overwrite_enabled"):
        build_design(source)


def test_allows_valid_bool_strings():
    source = _minimal_yaml().replace(
        "class: DesignPlanar",
        'class: DesignPlanar\n    enable_renderers: "false"',
    ).replace('size: ["${circuit.Q1.pad_width}", 90um]',
              'size: ["${circuit.Q1.pad_width}", 90um], subtract: "true"', 1)

    design = build_design(source)
    q1_id = design.components["Q1"].id
    q1_rows = design.qgeometry.tables["poly"][
        design.qgeometry.tables["poly"]["component"] == q1_id]

    assert len(design.renderers) == 0
    assert bool(q1_rows.iloc[0]["subtract"]) is True


def test_default_export_does_not_inject_renderer_qgeometry_defaults():
    register_design("RendererDefaultDesign", RendererDefaultDesign)
    try:
        source = _minimal_yaml().replace("class: DesignPlanar",
                                         "class: RendererDefaultDesign").replace(
                                             "type: path.line",
                                             "type: junction.line", 1)
        design = build_design(source)
    finally:
        clear_user_registry()

    assert len(design.renderers) == 0
    assert len(design.qgeometry.tables["junction"]) == 1
    assert "dummy_inductance" not in design.qgeometry.tables["junction"].columns


def test_resolved_transforms_are_preserved_in_chain_metadata():
    source = _minimal_yaml().replace(
        "components:",
        'transforms:\n    Q1: {translate: ["${qx}", 0mm]}\n  components:',
        1,
    )

    ir = build_ir(source)
    design = build_design(source)

    assert ir.geometry["transforms"]["Q1"]["translate"] == ["1.0mm", "0mm"]
    assert design.metadata["dsl_chain"]["geometry"]["transforms"] == ir.geometry[
        "transforms"]


def test_template_extend_requires_template_name():
    source = """
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  templates:
    base:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [1mm, 1mm]}
    child:
      $extend: []
  components:
    Q1:
      $extend: child
"""

    with pytest.raises(DesignDslError,
                       match="extend value must be a template name"):
        build_ir(source)


@pytest.mark.parametrize("bad_metadata", [
    "metadata: []",
    "metadata: ''",
    "metadata: false",
])
def test_rejects_non_mapping_component_metadata(bad_metadata):
    source = _minimal_yaml().replace("primitives:",
                                     f"{bad_metadata}\n      primitives:", 1)
    with pytest.raises(DesignDslError, match="metadata must be a mapping"):
        build_ir(source)


@pytest.mark.parametrize("source, message", [
    ("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    - name: Q1
      pins:
        - {name: bus, points: [[0mm, -6um], [0mm, 6um]], width: 12um}
    - name: Q1
      pins:
        - {name: bus, points: [[0mm, -6um], [0mm, 6um]], width: 12um}
""", "Duplicate component name"),
    ("""
schema: qiskit-metal/design-dsl/3
vars: {}
hamiltonian: {}
circuit: {}
netlist: {}
geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      primitives:
        - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [1mm, 1mm]}
        - {name: pad, type: poly.rectangle, center: [1mm, 0mm], size: [1mm, 1mm]}
""", "Duplicate primitive"),
    (_minimal_yaml("""
    Q3:
      pins:
        - {name: bus, points: [[0mm, -6um], [0mm, 6um]], width: 12um}
        - {name: bus, points: [[0.1mm, -6um], [0.1mm, 6um]], width: 12um}
"""), "Duplicate pin"),
])
def test_rejects_duplicate_names(source, message):
    with pytest.raises(DesignDslError, match=message):
        build_ir(source)


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


def test_build_design_errors_for_missing_netlist_pin():
    with pytest.raises(DesignDslError, match="unknown pin"):
        build_design(_minimal_yaml().replace("Q2.bus", "Q2.nope"))


@pytest.mark.parametrize("replacement, message", [
    ("chip: missing_chip", "Primitive Q1.pad references unknown chip"),
    ("width: \"${trace_w}\", gap: \"${trace_gap}\", chip: missing_chip",
     "Pin Q1.bus references unknown chip"),
])
def test_export_rejects_unknown_primitive_or_pin_chip(replacement, message):
    if replacement.startswith("chip"):
        source = _minimal_yaml().replace(
            'size: ["${circuit.Q1.pad_width}", 90um]',
            f'size: ["${{circuit.Q1.pad_width}}", 90um], {replacement}',
        )
    else:
        source = _minimal_yaml().replace(
            'width: "${trace_w}", gap: "${trace_gap}"',
            replacement,
            1,
        )
    with pytest.raises(DesignDslError, match=message):
        build_design(source)
