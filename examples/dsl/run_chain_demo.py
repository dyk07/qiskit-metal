# -*- coding: utf-8 -*-
"""Run a Hamiltonian/Circuit/Netlist/Geometry DSL example.

Usage:
    python examples/dsl/run_chain_demo.py
    python examples/dsl/run_chain_demo.py --yaml examples/dsl/chain_2q_netlist.metal.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _summarize_chain(design) -> str:
    chain = design.metadata.get("dsl_chain", {})
    hamiltonian = chain.get("hamiltonian") or {}
    circuit = chain.get("circuit") or {}
    netlist = chain.get("netlist") or {}

    lines = [
        f"chain schema : {chain.get('schema')}",
        f"hamiltonian  : {list(hamiltonian.keys()) if isinstance(hamiltonian, dict) else type(hamiltonian).__name__}",
        f"circuit keys : {', '.join(circuit.keys()) if isinstance(circuit, dict) else type(circuit).__name__}",
        f"netlist conns: {len(netlist.get('connections', [])) if isinstance(netlist, dict) else 0}",
        f"net_info rows: {len(design.net_info)}",
    ]

    if "Q1" in design.components:
        q1 = design.components["Q1"]
        pad_width = q1.options.get("pad_width")
        if isinstance(circuit, dict) and "Q1" in circuit:
            lines.append(
                f"Q1.pad_width: {pad_width} (circuit: {circuit['Q1'].get('pad_width')})")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yaml",
        type=Path,
        default=_HERE.with_name("chain_2q_full.metal.yaml"),
        help="DSL YAML file path",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("QISKIT_METAL_HEADLESS", "1")

    from qiskit_metal.toolbox_metal.design_dsl import build_design

    design = build_design(args.yaml)
    print(_summarize_chain(design))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
