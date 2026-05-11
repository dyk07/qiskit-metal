# -*- coding: utf-8 -*-
"""Proof of bidirectional traversal for the chain DSL (2x2 example).

Checks:
  1) Circuit -> geometry (pad width propagation)
  2) Geometry -> netlist (routes populate net_info)
  3) Geometry -> circuit (explicit extractor)
  4) Round-trip (override circuit, rebuild, geometry updates)
"""

from __future__ import annotations

from pathlib import Path
import sys

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def extract_geometry_to_circuit(design) -> dict:
    """Collect geometry-derived values and store them in the chain metadata."""
    chain = design.metadata.get("dsl_chain", {})
    circuit = chain.setdefault("circuit", {})

    route_names = ["top_bus", "left_bus", "bottom_bus", "right_bus"]
    route_lengths: dict[str, str] = {}
    for name in route_names:
        if name in design.components:
            length = design.components[name].options.get("_actual_length")
            if length:
                route_lengths[name] = str(length)

    circuit["route_lengths"] = route_lengths
    return route_lengths


def main() -> int:
    from qiskit_metal.toolbox_metal.design_dsl import build_design

    yaml_path = _HERE.with_name("2x2_4qubit.chain.metal.yaml")
    design = build_design(yaml_path)
    chain = design.metadata.get("dsl_chain", {})

    # 1) Circuit -> geometry
    pad_circuit = str(chain["circuit"]["Q1"]["pad_width"])
    pad_geom = str(design.components["Q1"].options.get("pad_width"))
    assert pad_geom == pad_circuit, "Circuit -> geometry propagation failed"

    # 2) Geometry -> netlist (routes populate net_info)
    assert len(design.net_info) > 0, "Routes did not populate net_info"

    # 3) Geometry -> circuit (explicit extractor)
    route_lengths = extract_geometry_to_circuit(design)
    assert route_lengths, "No route lengths extracted from geometry"

    # 4) Round-trip: override circuit and rebuild
    override_circuit = dict(chain["circuit"])
    for qubit in ("Q1", "Q2", "Q3", "Q4"):
        override_circuit[qubit] = dict(override_circuit[qubit])
        override_circuit[qubit]["pad_width"] = "450um"

    design2 = build_design(yaml_path, overrides={"circuit": override_circuit})
    pad_geom_2 = str(design2.components["Q1"].options.get("pad_width"))
    assert pad_geom_2 == "450um", "Round-trip override failed"

    print("PASS: circuit -> geometry")
    print("PASS: geometry -> netlist")
    print("PASS: geometry -> circuit (extractor)")
    print("PASS: circuit override -> geometry (round-trip)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
