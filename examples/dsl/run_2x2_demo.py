# -*- coding: utf-8 -*-
"""跑通 2x2 4-qubit DSL 示例的最小脚本（headless 友好）。

运行：
    cd qiskit-metal-worktrees/dyk07-main
    python examples/dsl/run_2x2_demo.py            # 仅打印摘要
    python examples/dsl/run_2x2_demo.py --gui      # 顺便开 GUI

设计目标：用 ~30 行 Python + 一份 YAML 替代原本 ~230 行的 2x2 demo。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 让脚本既能从仓库根直接跑，也能在没装 qiskit-metal pkg 时从 src 走
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _summarize(design) -> str:
    lines = [
        f"design class : {design.__class__.__name__}",
        f"chip size    : {design.chips.main.size.size_x} x "
        f"{design.chips.main.size.size_y}",
        f"variables    : {dict(design.variables)}",
        f"components   : {len(design.components)}",
    ]
    for name, component in design.components.items():
        pin_names = ", ".join(component.pins.keys()) or "<no pins>"
        lines.append(f"  - {name:<10s} {component.__class__.__name__:<14s} "
                     f"pins: {pin_names}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yaml", type=Path,
                        default=_HERE.with_name("2x2_4qubit.metal.yaml"),
                        help="DSL YAML 文件路径")
    parser.add_argument("--gui", action="store_true",
                        help="构建后启动 MetalGUI")
    args = parser.parse_args(argv)

    if not args.gui:
        os.environ.setdefault("QISKIT_METAL_HEADLESS", "1")

    from qiskit_metal.toolbox_metal.design_dsl import build_design

    design = build_design(args.yaml)
    print(_summarize(design))

    if args.gui:
        from qiskit_metal import MetalGUI
        try:
            from PySide6.QtWidgets import QApplication
        except ModuleNotFoundError:
            from PySide2.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
        gui = MetalGUI(design)
        gui.rebuild()
        gui.autoscale()
        gui.main_window.show()
        return app.exec_()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
