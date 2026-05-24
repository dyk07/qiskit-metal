# -*- coding: utf-8 -*-
"""DSL v3 双向追踪验证（基于 chain_2q_native.metal.yaml）。

证明四条链路:

  1) circuit -> geometry: circuit.Q*.pad_width 通过 ${...} 插值传到 primitive 尺寸
  2) netlist  -> net_info: netlist.connections 写入 design.net_info
  3) geometry -> circuit:  从 derived metadata 取出 bus 的实际 path 长度
  4) round-trip:           overrides 改 circuit 后重建，geometry 同步更新
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _pad_left_x_extent(derived, qubit: str) -> float:
    bounds = derived["circuit"]["geometry"][qubit]["primitives"]["pad_left"]["bounds"]
    return bounds[2] - bounds[0]


def main() -> int:
    from qiskit_metal.toolbox_metal.dsl import build_design

    yaml_path = _HERE.with_name("chain_2q_native.metal.yaml")
    design = build_design(yaml_path)
    chain = design.metadata["dsl_chain"]
    derived = chain["derived"]

    # 1) circuit -> geometry：pad_width 从 circuit 插值到 primitive
    pad_circuit = chain["circuit"]["Q1"]["pad_width"]          # "420um"
    pad_geom_mm = _pad_left_x_extent(derived, "Q1")            # 0.42
    assert abs(pad_geom_mm - 0.42) < 1e-9, (
        f"circuit -> geometry 失败: pad_width={pad_circuit}, geom={pad_geom_mm}")

    # 2) netlist -> net_info：connections 写入 net_info
    assert len(design.net_info) > 0, "netlist -> net_info 失败：net_info 为空"

    # 3) geometry -> circuit：从 derived 取 bus path 长度，写回 circuit
    bus_length_mm = derived["circuit"]["geometry"]["bus"]["primitives"]["center_trace"]["length"]
    chain["circuit"].setdefault("bus", {})["actual_length"] = f"{bus_length_mm}mm"
    assert bus_length_mm > 0, "geometry -> circuit 失败：bus 长度为 0"

    # 4) round-trip：覆盖 circuit.Q1.pad_width 后重建，geometry 同步变化
    design2 = build_design(
        yaml_path,
        overrides={"circuit": {"Q1": {"pad_width": "500um"}}},
    )
    pad_geom_mm_2 = _pad_left_x_extent(
        design2.metadata["dsl_chain"]["derived"], "Q1")
    assert abs(pad_geom_mm_2 - 0.5) < 1e-9, (
        f"round-trip 失败：override 后 geom pad_width={pad_geom_mm_2}")

    print("PASS: circuit -> geometry            "
          f"(Q1.pad_width={pad_circuit} -> pad_left x-span={pad_geom_mm}mm)")
    print(f"PASS: netlist  -> net_info            (net rows={len(design.net_info)})")
    print(f"PASS: geometry -> circuit (extractor) (bus length={bus_length_mm}mm)")
    print(f"PASS: circuit override -> geometry    (Q1 pad_width 420um -> 500um)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
