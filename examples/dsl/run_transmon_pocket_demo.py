# -*- coding: utf-8 -*-
"""Run the YAML-native TransmonPocket template example."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _table_names(design, table: str) -> list[str]:
    return sorted(design.qgeometry.tables[table]["name"].tolist())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "yaml",
        nargs="?",
        default=str(_HERE.parent / "transmon_pocket_2q.metal.yaml"),
    )
    args = parser.parse_args()

    from qiskit_metal.toolbox_metal.design_dsl import build_design, build_ir

    yaml_path = Path(args.yaml)
    ir = build_ir(yaml_path)
    design = build_design(yaml_path)
    chain = design.metadata["dsl_chain"]

    component_names = [component.name for component in ir.components]
    component_types = {
        name: chain["geometry"]["components"][name].get("type")
        for name in component_names
    }
    template_info = {
        name: design.components[name].metadata["template"]
        for name in component_names
    }
    pins = {
        name: sorted(design.components[name].pins)
        for name in component_names
    }

    print(f"schema       : {ir.schema}")
    print(f"components   : {component_names}")
    print(f"types        : {component_types}")
    print(f"templates    : {template_info}")
    print(f"poly rows    : {len(design.qgeometry.tables['poly'])} "
          f"{_table_names(design, 'poly')}")
    print(f"path rows    : {len(design.qgeometry.tables['path'])} "
          f"{_table_names(design, 'path')}")
    print(f"junction rows: {len(design.qgeometry.tables['junction'])} "
          f"{_table_names(design, 'junction')}")
    print(f"pins         : {pins}")
    print(f"net rows     : {len(design.net_info)}")
    print(f"metadata     : {sorted(chain)}")

    assert component_names == ["Q1", "Q2"]
    assert component_types == {"Q1": "transmon_pocket", "Q2": "transmon_pocket"}
    assert template_info == {
        "Q1": {
            "type": "transmon_pocket",
            "inherited": ["qcomponent", "base_qubit", "transmon_pocket"],
        },
        "Q2": {
            "type": "transmon_pocket",
            "inherited": ["qcomponent", "base_qubit", "transmon_pocket"],
        },
    }
    assert all(
        design.components[name].__class__.__name__ == "NativeComponent"
        for name in component_names
    )
    assert _table_names(design, "poly").count("pad_top") == 2
    assert _table_names(design, "poly").count("pad_bot") == 2
    assert _table_names(design, "poly").count("rect_pk") == 2
    assert _table_names(design, "poly").count("readout_connector_pad") == 2
    assert _table_names(design, "path").count("readout_wire") == 2
    assert _table_names(design, "path").count("readout_wire_sub") == 2
    assert _table_names(design, "junction").count("rect_jj") == 2
    assert pins == {"Q1": ["readout"], "Q2": ["readout"]}
    assert len(design.net_info) == 2
    assert int(design.components["Q1"].pins["readout"].net_id) == int(
        design.components["Q2"].pins["readout"].net_id
    )

    print("PASS: YAML-native TransmonPocket template exported to Metal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
