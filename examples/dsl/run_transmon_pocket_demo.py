# -*- coding: utf-8 -*-
"""运行 YAML-native TransmonPocket 模板示例。

这个脚本适合作为汇报中的第二段 demo:

1. 读取 ``transmon_pocket_2q.metal.yaml``。
2. 调用 ``build_ir()`` 展开 ``type: transmon_pocket`` 模板。
3. 调用 ``build_design()`` 导出到普通 Metal ``QDesign``。
4. 打印模板继承信息、qgeometry row names、generated pins 和 netlist。

重点观察:

- components 的 type 是 ``transmon_pocket``。
- 实际导出的 component class 是 ``NativeComponent``。
- qgeometry 中出现 YAML 模板生成的 pad/pocket/junction/readout rows。
- ``Q1.readout`` 和 ``Q2.readout`` 被连接到同一个 Metal net。
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


# 允许直接从源码树运行示例，而不要求先 pip install 当前 worktree。
_HERE = Path(__file__).resolve()
_REPO = _HERE.parents[2]
_SRC = _REPO / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


def _table_names(design, table: str) -> list[str]:
    """返回某张 qgeometry 表中的 row name，便于展示模板生成了什么。"""
    return sorted(design.qgeometry.tables[table]["name"].tolist())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the YAML-native TransmonPocket DSL demo."
    )
    parser.add_argument(
        "yaml",
        nargs="?",
        default=str(_HERE.parent / "transmon_pocket_2q.metal.yaml"),
        help="要构建的 DSL v3 YAML 文件；默认使用 transmon_pocket_2q.metal.yaml。",
    )
    args = parser.parse_args()

    # design_dsl 是兼容 facade；真实实现位于
    # qiskit_metal.toolbox_metal.dsl.builder。
    from qiskit_metal.toolbox_metal.design_dsl import build_design, build_ir

    yaml_path = Path(args.yaml)

    # build_ir() 会把 type: transmon_pocket 展开成 ComponentIR，
    # 其中包含 primitives、pins、resolved options、template metadata。
    ir = build_ir(yaml_path)

    # build_design() 会把 IR 写进 Metal QDesign:
    # qgeometry -> design.qgeometry.tables
    # pins      -> design.components[name].pins
    # netlist   -> design.net_info
    design = build_design(yaml_path)
    chain = design.metadata["dsl_chain"]

    component_names = [component.name for component in ir.components]

    # type 来自 resolved component source metadata。
    component_types = {
        name: chain["geometry"]["components"][name].get("type")
        for name in component_names
    }

    # template_info 会显示继承链:
    # qcomponent -> base_qubit -> transmon_pocket
    template_info = {
        name: design.components[name].metadata["template"]
        for name in component_names
    }

    # pins 展示 generator 是否真的生成了 readout pin。
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

    # 这些断言把 demo 变成 smoke test:
    # 如果 YAML 模板、生成器或导出逻辑变化，演示脚本会马上失败。
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

    # 关键边界: DSL build target 不是 qlibrary TransmonPocket class。
    assert all(
        design.components[name].__class__.__name__ == "NativeComponent"
        for name in component_names
    )

    # 静态 pocket 几何: pad_top/pad_bot/rect_pk/rect_jj。
    assert _table_names(design, "poly").count("pad_top") == 2
    assert _table_names(design, "poly").count("pad_bot") == 2
    assert _table_names(design, "poly").count("rect_pk") == 2

    # connection_pads.readout generator 生成的几何。
    assert _table_names(design, "poly").count("readout_connector_pad") == 2
    assert _table_names(design, "path").count("readout_wire") == 2
    assert _table_names(design, "path").count("readout_wire_sub") == 2
    assert _table_names(design, "junction").count("rect_jj") == 2

    # generated readout pins 和 netlist 连接。
    assert pins == {"Q1": ["readout"], "Q2": ["readout"]}
    assert len(design.net_info) == 2
    assert int(design.components["Q1"].pins["readout"].net_id) == int(
        design.components["Q2"].pins["readout"].net_id
    )

    print("PASS: YAML-native TransmonPocket template exported to Metal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
