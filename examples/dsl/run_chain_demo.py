# -*- coding: utf-8 -*-
"""运行 primitive-native full-chain DSL 示例。

这个脚本适合作为汇报中的第一段 demo:

1. 读取 ``chain_2q_native.metal.yaml``。
2. 调用 ``build_ir()``，证明 YAML 可以先解析成独立 IR。
3. 调用 ``build_design()``，证明 IR 可以导出到普通 Metal ``QDesign``。
4. 打印 qgeometry、netlist 和 derived metadata 的摘要。

默认运行:

    C:\\ProgramData\\anaconda3\\envs\\metal-env\\python.exe examples\\dsl\\run_chain_demo.py

也可以传入其它 YAML 文件:

    C:\\ProgramData\\anaconda3\\envs\\metal-env\\python.exe examples\\dsl\\run_chain_demo.py path\\to\\file.metal.yaml
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the native Hamiltonian-Circuit-Netlist-Geometry DSL demo."
    )
    parser.add_argument(
        "yaml",
        nargs="?",
        default=str(_HERE.parent / "chain_2q_native.metal.yaml"),
        help="要构建的 DSL v3 YAML 文件；默认使用 chain_2q_native.metal.yaml。",
    )
    args = parser.parse_args()

    # design_dsl 是兼容 facade；真实实现位于
    # qiskit_metal.toolbox_metal.dsl.builder。
    from qiskit_metal.toolbox_metal.design_dsl import build_design, build_ir

    yaml_path = Path(args.yaml)

    # build_ir() 只做解析、模板/插值展开、primitive/pin IR 生成和 derived 计算。
    # 它返回的 ir.components / ir.derived 适合调试和单元测试。
    ir = build_ir(yaml_path)

    # build_design() 内部会再次 build_ir()，然后 export_ir_to_metal()。
    # 导出结果是普通 Metal QDesign: qgeometry、pins、net_info 都在里面。
    design = build_design(yaml_path)
    chain = design.metadata["dsl_chain"]

    # 这些打印值对应汇报里最容易说明的落点:
    # - components 来自 DesignIR
    # - qgeometry rows 来自 design.qgeometry.tables
    # - net rows 来自 design.net_info
    # - derived keys 来自 design.metadata["dsl_chain"]["derived"]
    print(f"schema       : {ir.schema}")
    print(f"components   : {[component.name for component in ir.components]}")
    print(f"poly rows    : {len(design.qgeometry.tables['poly'])}")
    print(f"path rows    : {len(design.qgeometry.tables['path'])}")
    print(f"junction rows: {len(design.qgeometry.tables['junction'])}")
    print(f"net rows     : {len(design.net_info)}")
    print(f"derived keys : {sorted(chain['derived'])}")

    # 断言让这个 demo 同时充当 smoke test。示例结构改变时，
    # 这里能第一时间提醒 qgeometry/netlist 输出也要同步更新。
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
