# -*- coding: utf-8 -*-

"""DSL → Gmsh adapter 演练脚本 (M3): 把 chain_2q_native YAML 跑到 ``.msh``。

与 ``run_chain_demo.py`` 配对: 后者证明 IR 能导出到普通 Metal ``QDesign``;
本脚本证明同一个 YAML 可以 **绕过 QDesign / QGmshRenderer**, 直接经
``build_mesh`` 产出 Gmsh 网格 + named physical groups, 作为下游 EM 求解
器的几何前端。

默认运行:

    C:\\ProgramData\\anaconda3\\envs\\metal-env\\python.exe \\
        examples\\dsl\\run_chain_gmsh_demo.py --output build\\chain_2q.msh

也可以打开 Gmsh GUI 直观看几何:

    C:\\ProgramData\\anaconda3\\envs\\metal-env\\python.exe \\
        examples\\dsl\\run_chain_gmsh_demo.py --gui

或传入其它 YAML:

    ... examples\\dsl\\run_chain_gmsh_demo.py path\\to\\file.metal.yaml \\
        --output build\\out.msh
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


# 允许直接从源码树运行示例, 与其它 run_*_demo.py 一致。
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# 演示用粗 mesh, 把 mesh.generate 时间控制到秒级 (default 5um 的 size 在
# 普通笔记本上能让生成 mesh 达到 100MB+; 这里 ~mm 量级足以让 reviewer
# 在 GUI 里看 group 划分而不是测试 solver 精度)。单位 = mm。
_DEMO_MESH = {
    "max_size": 2.0,        # 2 mm
    "min_size": 0.5,        # 500 um
    "max_size_jj": 0.5,
    "conductor_refine": {"min_dist": 1.0, "max_dist": 3.0},
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a Gmsh .msh from a DSL v3 YAML via build_mesh().")
    parser.add_argument(
        "yaml", nargs="?",
        default=str(_HERE.parent / "chain_2q_native.metal.yaml"),
        help="要构建的 DSL v3 YAML 文件; 默认 chain_2q_native.metal.yaml。")
    parser.add_argument(
        "--output", "-o", default=None,
        help="输出 .msh 路径; 不指定时不写文件 (仅在内存生成 mesh)。")
    parser.add_argument(
        "--gui", action="store_true",
        help="生成后调 gmsh.fltk.run() 打开 GUI 看几何 / 网格 / physical groups。")
    parser.add_argument(
        "--fine", action="store_true",
        help="用 schema 自带的精细 mesh 设置 (default 演示是粗 mesh)。")
    args = parser.parse_args()

    from qiskit_metal.toolbox_metal.dsl.gmsh_adapter import build_mesh

    yaml_path = Path(args.yaml)
    output_path = Path(args.output) if args.output else None

    options: dict = {}
    if not args.fine:
        options["mesh"] = _DEMO_MESH

    result = build_mesh(
        yaml_path,
        output_path=output_path,
        options=options or None,
        show_gui=args.gui,
    )

    # 摘要 — 与 run_chain_demo.py 风格一致, 适合放汇报里。
    bbox = result.bounding_box_m
    print(f"schema           : {result.ir.schema}")
    print(f"components       : {[c.name for c in result.ir.components]}")
    print(f"bounding_box (m) : xmin={bbox[0]:.4g}, ymin={bbox[1]:.4g}, "
          f"xmax={bbox[2]:.4g}, ymax={bbox[3]:.4g}")
    if result.mesh_path is not None:
        print(f"mesh file        : {result.mesh_path}")
        print(f"mesh size (bytes): {result.mesh_path.stat().st_size}")
    else:
        print("mesh file        : (not written; pass --output to write .msh)")
    print(f"physical groups  : {len(result.physical_groups)}")
    for name, (dim, tags) in sorted(result.physical_groups.items()):
        print(f"  - {name} (dim={dim}, n_tags={len(tags)})")

    # 同 run_chain_demo.py: assert 让本脚本也当 smoke test 用。
    required = ["gnd_layer1", "substrate_layer3", "vacuum",
                "Q1_pad_left", "bus_center_trace", "vacuum_outer"]
    for name in required:
        assert name in result.physical_groups, (
            f"physical group {name!r} missing (got "
            f"{sorted(result.physical_groups)})")
    print("PASS: native DSL chain meshed via gmsh_adapter")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
