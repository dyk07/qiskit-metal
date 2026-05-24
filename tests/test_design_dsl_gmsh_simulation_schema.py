# -*- coding: utf-8 -*-
"""测试 ``simulation`` YAML 段在 ``build_ir`` 里的解析。

只覆盖 schema / 解析 / 校验路径; 不依赖 ``gmsh`` 也不构造 ``QDesign``。
"""

from __future__ import annotations

import pytest

from qiskit_metal.toolbox_metal.design_dsl import (
    CURRENT_SCHEMA,
    DesignDslError,
    build_ir,
)


def _yaml_with_simulation(simulation_block: str) -> str:
    return f"""
schema: {CURRENT_SCHEMA}
vars:
  air_top: 890um
  pad_w: 400um
hamiltonian:
  subsystems:
    Q1: {{EJ: 18GHz}}
circuit:
  Q1: {{pad_width: "${{pad_w}}"}}
netlist:
  connections: []
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
           width: 12um, gap: 7um}}
{simulation_block}
"""


def test_missing_simulation_yields_empty_dict():
    ir = build_ir(_yaml_with_simulation(""))
    assert ir.simulation == {}
    # to_metadata 也带 simulation 字段
    assert "simulation" in ir.to_metadata()
    assert ir.to_metadata()["simulation"] == {}


def test_full_simulation_block_parses_and_resolves_units():
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um, z: 0um, material: pec}
      3: {kind: dielectric, thickness: -750um, z: 0um, material: silicon, eps_r: 11.45}
    airbox:
      top: "${air_top}"
      bottom: 1650um
      side_buffer: 200um
    ports:
      - {pin: Q1.bus, type: lumped, impedance: 50ohm, value: 1.0}
    symmetry:
      - {plane: y0, condition: pec}
    mesh:
      max_size: 70um
      min_size: 5um
      max_size_jj: 5um
      conductor_refine: {min_dist: 10um, max_dist: 130um}
    output: {format: msh4, scaling: 1.0}
"""
    ir = build_ir(_yaml_with_simulation(block))
    sim = ir.simulation
    assert set(sim.keys()) == {"gmsh"}
    gmsh = sim["gmsh"]

    # 长度字面量在 IR 里是 mm float, 和 PrimitiveIR.geometry 单位一致。
    assert gmsh["layer_stack"][1]["thickness"] == pytest.approx(0.002)
    assert gmsh["layer_stack"][3]["thickness"] == pytest.approx(-0.75)
    assert gmsh["layer_stack"][1]["material"] == "pec"
    assert gmsh["layer_stack"][3]["eps_r"] == pytest.approx(11.45)

    # ${...} 被 vars 解析。
    assert gmsh["airbox"]["top"] == pytest.approx(0.89)
    assert gmsh["airbox"]["bottom"] == pytest.approx(1.65)
    assert gmsh["airbox"]["side_buffer"] == pytest.approx(0.2)

    # 端口被拆成 component + pin。
    assert gmsh["ports"] == [{
        "component": "Q1",
        "pin": "bus",
        "type": "lumped",
        "impedance": 50.0,
        "value": 1.0,
    }]

    assert gmsh["symmetry"] == [{"plane": "y0", "condition": "pec"}]
    assert gmsh["mesh"]["max_size"] == pytest.approx(0.07)
    assert gmsh["mesh"]["conductor_refine"]["min_dist"] == pytest.approx(0.01)
    assert gmsh["output"] == {"format": "msh4", "scaling": 1.0}


def test_simulation_must_be_mapping():
    block = """
simulation: []
"""
    with pytest.raises(DesignDslError, match="simulation must be a mapping"):
        build_ir(_yaml_with_simulation(block))


def test_simulation_rejects_unknown_top_level_key():
    block = """
simulation:
  ansys: {}
"""
    with pytest.raises(DesignDslError, match="Unknown simulation"):
        build_ir(_yaml_with_simulation(block))


def test_simulation_gmsh_rejects_unknown_key():
    block = """
simulation:
  gmsh:
    nonsense: 1
"""
    with pytest.raises(DesignDslError, match="Unknown simulation.gmsh"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_requires_thickness():
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, z: 0um}
"""
    with pytest.raises(DesignDslError,
                       match=r"layer_stack\[1\]\.thickness is required"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_rejects_unknown_kind():
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: superconductor, thickness: 2um}
"""
    with pytest.raises(DesignDslError, match=r"\.kind must be one of"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_rejects_non_int_key():
    block = """
simulation:
  gmsh:
    layer_stack:
      foo: {kind: metal, thickness: 2um}
"""
    with pytest.raises(DesignDslError, match="layer_stack key must be int"):
        build_ir(_yaml_with_simulation(block))


def test_port_pin_must_reference_known_component():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q9.bus, type: lumped}
"""
    with pytest.raises(DesignDslError,
                       match=r"unknown component 'Q9'"):
        build_ir(_yaml_with_simulation(block))


def test_port_pin_must_reference_known_pin():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q1.missing, type: ground}
"""
    with pytest.raises(DesignDslError,
                       match=r"unknown pin Q1\.missing"):
        build_ir(_yaml_with_simulation(block))


def test_port_pin_must_have_dot_separator():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q1bus, type: lumped}
"""
    with pytest.raises(DesignDslError,
                       match=r"\.pin must be 'component.pin'"):
        build_ir(_yaml_with_simulation(block))


def test_port_type_validated():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q1.bus, type: scattering}
"""
    with pytest.raises(DesignDslError, match=r"\.type must be one of"):
        build_ir(_yaml_with_simulation(block))


def test_port_endpoint_reuse_rejected():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q1.bus, type: lumped}
      - {pin: Q1.bus, type: ground}
"""
    with pytest.raises(DesignDslError, match=r"reuses endpoint Q1\.bus"):
        build_ir(_yaml_with_simulation(block))


def test_symmetry_plane_validated():
    block = """
simulation:
  gmsh:
    symmetry:
      - {plane: z45, condition: pec}
"""
    with pytest.raises(DesignDslError, match=r"\.plane must be one of"):
        build_ir(_yaml_with_simulation(block))


def test_symmetry_condition_validated():
    block = """
simulation:
  gmsh:
    symmetry:
      - {plane: y0, condition: open}
"""
    with pytest.raises(DesignDslError, match=r"\.condition must be one of"):
        build_ir(_yaml_with_simulation(block))


def test_symmetry_plane_no_duplicates():
    block = """
simulation:
  gmsh:
    symmetry:
      - {plane: y0, condition: pec}
      - {plane: y0, condition: pmc}
"""
    with pytest.raises(DesignDslError, match=r"plane 'y0' declared twice"):
        build_ir(_yaml_with_simulation(block))


def test_airbox_rejects_negative():
    block = """
simulation:
  gmsh:
    airbox: {top: -890um}
"""
    with pytest.raises(DesignDslError, match=r"airbox\.top must be > 0"):
        build_ir(_yaml_with_simulation(block))


def test_mesh_max_size_must_be_positive():
    block = """
simulation:
  gmsh:
    mesh: {max_size: 0um}
"""
    with pytest.raises(DesignDslError, match=r"mesh\.max_size must be > 0"):
        build_ir(_yaml_with_simulation(block))


def test_impedance_unit_validated():
    block = """
simulation:
  gmsh:
    ports:
      - {pin: Q1.bus, type: lumped, impedance: 50km}
"""
    with pytest.raises(DesignDslError, match=r"\.impedance has unsupported unit"):
        build_ir(_yaml_with_simulation(block))


def test_port_defaults_to_lumped_when_type_missing():
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um}
    ports:
      - {pin: Q1.bus}
"""
    ir = build_ir(_yaml_with_simulation(block))
    assert ir.simulation["gmsh"]["ports"][0]["type"] == "lumped"


def test_symmetry_condition_defaults_to_pec():
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um}
    symmetry:
      - {plane: x0}
"""
    ir = build_ir(_yaml_with_simulation(block))
    assert ir.simulation["gmsh"]["symmetry"][0]["condition"] == "pec"


# --- M1 r1 必修补丁 ----------------------------------------------------------

def test_layer_stack_required_when_gmsh_present():
    """plan §0: gmsh 段一旦出现, layer_stack 必填。"""
    block = """
simulation:
  gmsh:
    airbox: {top: 890um}
"""
    with pytest.raises(DesignDslError,
                       match="simulation.gmsh.layer_stack is required"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_empty_rejected():
    block = """
simulation:
  gmsh:
    layer_stack: {}
"""
    with pytest.raises(DesignDslError,
                       match="layer_stack must declare at least one layer"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_requires_metal_layer():
    """stack 里至少要有一个 kind=metal, 不能只有 dielectric。"""
    block = """
simulation:
  gmsh:
    layer_stack:
      3: {kind: dielectric, thickness: -750um}
"""
    with pytest.raises(DesignDslError,
                       match="must contain at least one metal layer"):
        build_ir(_yaml_with_simulation(block))


def test_layer_stack_must_cover_primitive_layers():
    """primitive 引用的 layer 必须全部出现在 stack 里 (当 stack 出现时)。

    `_yaml_with_simulation` 中 Q1.pad 默认 layer=1; 这里改成 layer=2,
    但 stack 里只声明 layer=1, schema 必须报错。
    """
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 2um}
"""
    yaml_text = _yaml_with_simulation(block).replace(
        "{name: pad, type: poly.rectangle, center: [0mm, 0mm],",
        "{name: pad, type: poly.rectangle, center: [0mm, 0mm], layer: 2,")
    with pytest.raises(
            DesignDslError,
            match=r"layer_stack missing layer\(s\) referenced by primitives"):
        build_ir(yaml_text)


def test_layer_stack_thickness_zero_rejected():
    """B1: thickness=0 让 extrude 退化, schema 拦掉。"""
    block = """
simulation:
  gmsh:
    layer_stack:
      1: {kind: metal, thickness: 0um}
"""
    with pytest.raises(DesignDslError,
                       match=r"thickness must be non-zero"):
        build_ir(_yaml_with_simulation(block))
