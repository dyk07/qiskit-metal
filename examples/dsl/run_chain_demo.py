# -*- coding: utf-8 -*-
"""Run the native Hamiltonian-Circuit-Netlist-Geometry DSL example."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("yaml",
                        nargs="?",
                        default=str(_HERE.parent / "chain_2q_native.metal.yaml"))
    args = parser.parse_args()

    from qiskit_metal.toolbox_metal.design_dsl import build_design, build_ir

    yaml_path = Path(args.yaml)
    ir = build_ir(yaml_path)
    design = build_design(yaml_path)
    chain = design.metadata["dsl_chain"]

    print(f"schema       : {ir.schema}")
    print(f"components   : {[component.name for component in ir.components]}")
    print(f"poly rows    : {len(design.qgeometry.tables['poly'])}")
    print(f"path rows    : {len(design.qgeometry.tables['path'])}")
    print(f"junction rows: {len(design.qgeometry.tables['junction'])}")
    print(f"net rows     : {len(design.net_info)}")
    print(f"derived keys : {sorted(chain['derived'])}")

    assert len(ir.components) == 3
    assert len(design.qgeometry.tables["poly"]) >= 4
    assert len(design.qgeometry.tables["path"]) >= 1
    assert len(design.net_info) == 4
    assert chain["derived"]["circuit"]["geometry"]["bus"]["primitives"][
        "center_trace"]["length"] > 0
    print("PASS: native DSL chain exported to Metal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
