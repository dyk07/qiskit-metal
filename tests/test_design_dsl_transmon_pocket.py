# -*- coding: utf-8 -*-
"""Focused parity tests for the YAML-native TransmonPocket template."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from qiskit_metal.designs import DesignPlanar
from qiskit_metal.qlibrary.qubits.transmon_pocket import TransmonPocket
from qiskit_metal.toolbox_metal.design_dsl import build_design, build_ir


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "dsl" / (
    "transmon_pocket_2q.metal.yaml")


def _transmon_source(orientation: float, loc_w: int, loc_h: int) -> str:
    return f"""
schema: qiskit-metal/design-dsl/3
vars:
  cpw_width: 12um
  cpw_gap: 7um
hamiltonian: {{}}
circuit: {{}}
netlist: {{}}
geometry:
  design: {{class: DesignPlanar}}
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: 1mm
        pos_y: 2mm
        orientation: {orientation}
        connection_pads:
          readout:
            loc_W: {loc_w}
            loc_H: {loc_h}
            cpw_width: "${{vars.cpw_width}}"
            cpw_gap: "${{vars.cpw_gap}}"
"""


def _qlibrary_reference(orientation: float, loc_w: int, loc_h: int):
    design = DesignPlanar(enable_renderers=False)
    TransmonPocket(
        design,
        "Q1",
        options={
            "pos_x": "1mm",
            "pos_y": "2mm",
            "orientation": str(orientation),
            "connection_pads": {
                "readout": {
                    "loc_W": str(loc_w),
                    "loc_H": str(loc_h),
                    "cpw_width": "12um",
                    "cpw_gap": "7um",
                },
            },
        },
    )
    return design


def _row_by_name(design, table: str, name: str):
    rows = design.qgeometry.tables[table]
    matches = rows[rows["name"] == name]
    assert len(matches) == 1
    return matches.iloc[0]


def _assert_geometry_matches(actual, expected):
    if actual.geom_type == "LineString":
        np.testing.assert_allclose(list(actual.coords), list(expected.coords),
                                   atol=1e-12)
    else:
        assert actual.symmetric_difference(expected).area == pytest.approx(
            0.0, abs=1e-12)


def _assert_table_matches(yaml_design, qlibrary_design, table: str,
                          names: set[str]):
    yaml_rows = yaml_design.qgeometry.tables[table]
    qlibrary_rows = qlibrary_design.qgeometry.tables[table]

    assert set(yaml_rows["name"]) == names
    assert set(qlibrary_rows["name"]) == names

    for name in names:
        yaml_row = _row_by_name(yaml_design, table, name)
        qlibrary_row = _row_by_name(qlibrary_design, table, name)
        _assert_geometry_matches(yaml_row["geometry"],
                                 qlibrary_row["geometry"])
        assert bool(yaml_row["subtract"]) is bool(qlibrary_row["subtract"])
        if "width" in yaml_row.index:
            assert yaml_row["width"] == pytest.approx(qlibrary_row["width"])


def test_two_transmon_template_example_builds_native_components_and_netlist():
    ir = build_ir(EXAMPLE)
    design = build_design(EXAMPLE)

    assert [component.name for component in ir.components] == ["Q1", "Q2"]
    assert {component.type for component in ir.components} == {"transmon_pocket"}
    assert all(
        design.components[name].__class__.__name__ == "NativeComponent"
        for name in ["Q1", "Q2"]
    )

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
    assert set(design.qgeometry.tables["junction"]["name"]) == {"rect_jj"}
    assert sorted(design.components["Q1"].pins) == ["readout"]
    assert sorted(design.components["Q2"].pins) == ["readout"]
    assert len(design.net_info) == 2
    assert int(design.components["Q1"].pins["readout"].net_id) == int(
        design.components["Q2"].pins["readout"].net_id)

    chain_components = design.metadata["dsl_chain"]["geometry"]["components"]
    assert chain_components["Q1"]["type"] == "transmon_pocket"
    assert chain_components["Q2"]["type"] == "transmon_pocket"


@pytest.mark.parametrize("orientation,loc_w,loc_h", [
    (0, 1, 1),
    (45, -1, 1),
    (123.4, 1, -1),
])
def test_yaml_transmon_pocket_matches_qlibrary_geometry_and_pin(
        orientation, loc_w, loc_h):
    yaml_design = build_design(_transmon_source(orientation, loc_w, loc_h))
    qlibrary_design = _qlibrary_reference(orientation, loc_w, loc_h)

    _assert_table_matches(
        yaml_design,
        qlibrary_design,
        "poly",
        {"pad_top", "pad_bot", "rect_pk", "readout_connector_pad"},
    )
    _assert_table_matches(
        yaml_design,
        qlibrary_design,
        "path",
        {"readout_wire", "readout_wire_sub"},
    )
    _assert_table_matches(yaml_design, qlibrary_design, "junction", {"rect_jj"})

    yaml_pin = yaml_design.components["Q1"].pins["readout"]
    qlibrary_pin = qlibrary_design.components["Q1"].pins["readout"]
    np.testing.assert_allclose(yaml_pin.points, qlibrary_pin.points,
                               atol=1e-12)
    np.testing.assert_allclose(yaml_pin.middle, qlibrary_pin.middle,
                               atol=1e-12)
    np.testing.assert_allclose(yaml_pin.normal, qlibrary_pin.normal,
                               atol=1e-12)
    np.testing.assert_allclose(yaml_pin.tangent, qlibrary_pin.tangent,
                               atol=1e-12)
    assert yaml_pin.width == pytest.approx(qlibrary_pin.width)
    assert yaml_pin.gap == pytest.approx(qlibrary_pin.gap)

