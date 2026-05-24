# -*- coding: utf-8 -*-
"""一次性生成 examples/dsl/gmsh_mesh_demo.ipynb。

只是把 cells 拼起来 dump 成 ipynb JSON, 没有依赖 nbformat。重跑会覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent


HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "gmsh_mesh_demo.ipynb"


def md(text: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": dedent(text).strip("\n").splitlines(keepends=True),
    }


def code(src: str) -> dict:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": dedent(src).strip("\n").splitlines(keepends=True),
    }


CELLS: list[dict] = []

CELLS.append(md("""
# DSL v3 → Gmsh 端到端演示

这个 notebook 目标只有一个：**让你亲眼看到 DSL YAML 里写的几何真的被
放进 mesh 软件 (Gmsh) 里, 并且可以喂给 EM 求解器。**

链路：

```
chain_2q_native.metal.yaml   ← DSL v3 描述
        │
        │  build_mesh()      ← src/qiskit_metal/toolbox_metal/dsl/gmsh_adapter.py
        ▼
GmshMeshResult              ← 含 .msh 路径 + physical groups + bbox
        │
        ├──► gmsh.model     ← 在内存中已生成的 OCC 几何 + 3D mesh
        ├──► .msh 文件      ← 下游求解器 (Elmer / HFSS / palace) 直接读
        └──► meshio 回读    ← 证明文件被第三方工具消费
```

运行要求: `metal-env` conda 环境 (Python 3.10-3.12 + qiskit-metal + gmsh + meshio)。
"""))

CELLS.append(md("## 0. 准备：导入 + 字体 + 路径"))

CELLS.append(code("""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

# 让 notebook 不依赖 `pip install -e .`: 把仓库源码塞进 sys.path
_HERE = Path.cwd()
_REPO = next(p for p in [_HERE, *_HERE.parents] if (p / "src" / "qiskit_metal").exists())
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

print("repo:", _REPO)
print("python:", sys.version.split()[0])
"""))

CELLS.append(code("""
# 中文字体设置 (跨平台, 跟用户全局偏好一致)
import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt


def set_chinese_font():
    candidates = [
        "SimHei", "Microsoft YaHei",
        "WenQuanYi Micro Hei", "WenQuanYi Zen Hei",
        "Noto Sans CJK SC", "Noto Sans CJK JP",
        "Source Han Sans CN", "Source Han Sans SC",
        "PingFang SC", "Heiti SC", "STHeiti",
        "Droid Sans Fallback",
    ]
    available = {f.name for f in fm.fontManager.ttflist}
    found = [f for f in candidates if f in available]
    plt.rcParams["font.sans-serif"] = found + ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    if not found:
        warnings.filterwarnings(
            "ignore", message="Glyph .* missing from current font")


set_chinese_font()
print("matplotlib:", matplotlib.__version__)
"""))

CELLS.append(md("""
## 1. 加载 DSL v3 YAML → IR

用 `build_ir()` 先把 YAML 文本解析成 `DesignIR` (纯数据, 不依赖 gmsh)。
这样我们可以在调 mesh 之前先把要送进 Gmsh 的几何 / 网表 / layer stack
检查一遍。
"""))

CELLS.append(code("""
from qiskit_metal.toolbox_metal.dsl.builder import build_ir

yaml_path = _REPO / "examples" / "dsl" / "chain_2q_native.metal.yaml"
ir = build_ir(yaml_path.read_text(encoding="utf-8"))

print(f"schema       : {ir.schema}")
print(f"components   : {[c.name for c in ir.components]}")
print(f"connections  : {len(ir.netlist.connections)}")
print(f"layer_stack  : {sorted((ir.simulation.get('gmsh') or {}).get('layer_stack', {}).keys())}")
print(f"airbox       : {(ir.simulation.get('gmsh') or {}).get('airbox')}")
"""))

CELLS.append(md("""
## 2. 调 `build_mesh()` → 让几何真的进 Gmsh

`build_mesh` 内部分 7 个 stage:

| Stage | 干什么 |
|---|---|
| A+B | primitives → PlaneSurface → extrude 成 3D 体 |
| B' | 自动 open-pin endcap + lumped/ground 端口 box |
| C  | ground plane + vacuum box |
| C' | symmetry 半空间切割 (可选) |
| D  | subtract primitives + endcap boxes 从 ground 上 cut 掉 |
| D' | 端口面解析 |
| E  | fragment 共面缝合 |
| F  | 物理组分配 (named regions) |
| G  | mesh size fields + generate(3) + 写 .msh |

为了演示快, 这里用粗 mesh (2 mm)。等真正算 S 参的时候才把 mesh 拧细。
"""))

CELLS.append(code("""
import gmsh
from qiskit_metal.toolbox_metal.dsl.gmsh_adapter import build_mesh

# 关键: 我们自己先 gmsh.initialize(), build_mesh 检测到已 init 就只调
# gmsh.clear(), 跑完不会 finalize — caller 持有 session, 下面 cell 才能
# 继续 query OCC entities。否则 build_mesh 默认会自己清场。
gmsh.initialize()

mesh_out = _REPO / "examples" / "dsl" / "outputs" / "chain_2q_demo.msh"
mesh_out.parent.mkdir(parents=True, exist_ok=True)

demo_mesh = {
    "max_size": 2.0,        # 2 mm, 粗 mesh
    "min_size": 0.5,        # 500 um
    "max_size_jj": 0.5,
    "conductor_refine": {"min_dist": 1.0, "max_dist": 3.0},
}

result = build_mesh(
    yaml_path,
    output_path=mesh_out,
    options={"mesh": demo_mesh},
    show_gui=False,        # 想看 GUI 改成 True (本机非 headless 才行)
)

assert gmsh.isInitialized(), \"caller-owned session 应保留 init 状态\"

bbox = result.bounding_box_m
print(f\"mesh file        : {result.mesh_path}\")
print(f\"mesh size (bytes): {result.mesh_path.stat().st_size:,}\")
print(f\"bounding box (m) : xmin={bbox[0]:.4g}, ymin={bbox[1]:.4g}, \"
      f\"xmax={bbox[2]:.4g}, ymax={bbox[3]:.4g}\")
print(f\"physical groups  : {len(result.physical_groups)}\")
"""))

CELLS.append(md("""
## 3. 几何真的进 Gmsh 了 — 直接问 `gmsh.model`

因为上一格 caller 自己 init 了 gmsh, `build_mesh` 跑完不会 finalize,
当前 model 还在。直接 query OCC 实体数, 作为"几何确实落地"的硬证据。
"""))

CELLS.append(code("""
ents_3d = gmsh.model.getEntities(dim=3)
ents_2d = gmsh.model.getEntities(dim=2)
ents_1d = gmsh.model.getEntities(dim=1)
ents_0d = gmsh.model.getEntities(dim=0)

print(f"OCC entities  3D: {len(ents_3d)}  (体)")
print(f"OCC entities  2D: {len(ents_2d)}  (面)")
print(f"OCC entities  1D: {len(ents_1d)}  (曲线)")
print(f"OCC entities  0D: {len(ents_0d)}  (顶点)")

# 物理组明细 — 每个 named region 对应下游求解器一个材料 / BC 标签
print("\\n--- physical groups ---")
for name, (dim, tags) in sorted(result.physical_groups.items()):
    print(f"  dim={dim}  n_tags={len(tags):>3}  {name}")
"""))

CELLS.append(md("""
## 4. 可视化 — 让人眼也能看见

把 DSL IR 里的 primitives 投影到 XY 平面, 画出 Q1 / bus / Q2 + ground bbox。
这是 *设计意图*; 第 5 步会用 meshio 回读 .msh 验证 mesh 真的覆盖了这些区域。
"""))

CELLS.append(code("""
import numpy as np
from matplotlib.patches import Rectangle

fig, ax = plt.subplots(figsize=(9, 5))

# 物理 bbox (SI 米 → mm 显示)
xmin, ymin, xmax, ymax = (v * 1e3 for v in result.bounding_box_m)
ax.add_patch(Rectangle((xmin, ymin), xmax - xmin, ymax - ymin,
                       fill=False, edgecolor="0.4", linestyle="--",
                       label="ground bbox"))

colors = {"Q1": "#1f77b4", "Q2": "#d62728", "bus": "#2ca02c"}
for comp in ir.components:
    c = colors.get(comp.name, "0.5")
    for prim in comp.primitives:
        geom = prim.geometry
        if geom is None:
            continue
        # shapely Polygon / LineString — 取 exterior / coords 画线
        if geom.geom_type == "Polygon":
            xs, ys = geom.exterior.coords.xy
            xs = [x for x in xs]; ys = [y for y in ys]
            alpha = 0.25 if prim.subtract else 0.6
            ax.fill(xs, ys, color=c, alpha=alpha,
                    edgecolor=c, linewidth=0.8)
        elif geom.geom_type == "LineString":
            xs, ys = geom.xy
            lw = max(prim.width * 1e3 * 0.5, 1.0) if prim.width else 1.0
            ax.plot(xs, ys, color=c, linewidth=lw,
                    alpha=0.3 if prim.subtract else 0.9)

ax.set_aspect("equal")
ax.set_xlabel("x (mm)")
ax.set_ylabel("y (mm)")
ax.set_title("DSL IR → XY 投影 (实色=金属, 半透明=subtract)")
for name, c in colors.items():
    ax.plot([], [], color=c, label=name, linewidth=4)
ax.legend(loc="upper right")
plt.tight_layout()
plt.show()
"""))

CELLS.append(md("""
## 5. 用 `meshio` 回读 .msh — 第三方工具消费

`build_mesh` 写出的 .msh 已经能直接喂给 Elmer / HFSS / palace。这里用
`meshio` 把它再读回来, 统计单元数和物理组, 证明文件没坏。
"""))

CELLS.append(code("""
import meshio

m = meshio.read(result.mesh_path)
print(f"nodes (points)        : {len(m.points):,}")
print(f"point dim             : {m.points.shape[1]}D")

total_cells = sum(len(cb.data) for cb in m.cells)
print(f"total cells           : {total_cells:,}")
print(f"cell blocks by type   :")
for cb in m.cells:
    print(f"  {cb.type:>10s} × {len(cb.data):>6,d}")

# meshio 把 gmsh physical groups 放进 m.field_data: name → (tag, dim)
print(f"\\nfield_data (physical) : {len(m.field_data)} groups")
for name, (tag, dim) in sorted(m.field_data.items()):
    print(f"  dim={dim}  tag={tag:>4d}  {name}")

required = ["gnd_layer1", "substrate_layer3", "vacuum"]
missing = [r for r in required if r not in m.field_data]
print()
print("required physical groups present:", not missing,
      ("(missing: " + ", ".join(missing) + ")") if missing else "")
"""))

CELLS.append(md("""
## 6. 可视化 mesh — 截 2D 切片

直接画 Gmsh 生成的 3D mesh 太密看不出东西; 画 z=0 平面附近的 2D 三角面就够了。
"""))

CELLS.append(code("""
from collections import defaultdict

# meshio 把 2D 三角形归在 cells 里 type=='triangle' 的 block
points = m.points  # (N, 3) in mm (build_mesh 默认 mesh_format=msh4 + scaling=1)
tri_blocks = [cb for cb in m.cells if cb.type == "triangle"]
if not tri_blocks:
    print("(没有 triangle block —— 当前 mesh 全是 3D tet)")
else:
    tri = np.vstack([cb.data for cb in tri_blocks])
    # 只保留 z ≈ 0 的三角面 (chip metal/substrate 接口)
    z_mid = points[:, 2].mean()
    cz = points[tri].mean(axis=1)[:, 2]
    keep = np.abs(cz - z_mid) < 1e-3   # ±1mm 容差
    tri = tri[keep]

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.triplot(points[:, 0], points[:, 1], tri,
               linewidth=0.3, color="0.3")
    ax.set_aspect("equal")
    ax.set_xlabel("x (mm)")
    ax.set_ylabel("y (mm)")
    ax.set_title(f"Gmsh mesh — z≈0 切面 ({len(tri):,} triangles)")
    plt.tight_layout()
    plt.show()
"""))

CELLS.append(md("""
## 7. 已经可以仿真 — 把 .msh 接上求解器

`chain_2q_demo.msh` 现在长这样:

- **3D 体**: `vacuum`, `substrate_layer3` (silicon, eps_r=11.45), `gnd_layer1` (PEC)
- **2D 面**: `vacuum_outer` (外边界), 每个 component primitive 都有一个 named surface
- **1D 曲线**: 各导体边界 (mesh refinement 已经在此 bias)

下游求解器要做的:
1. 读 .msh → 拿到 mesh + physical group 名字
2. 把 `gnd_layer1` 设成 PEC, `substrate_layer3` 设成 silicon 介质,
   `vacuum_outer` 设成 absorbing (或 PEC, 取决于研究目的)
3. 在 lumped port surface 上加激励 (当前 YAML 没声明 port — 见下一格)
4. 求解 capacitance / S-parameters

下面给个最小的 Elmer SIF 片段作为示意 (不实际跑 Elmer):
"""))

CELLS.append(code("""
sif_snippet = '''
Header
  Mesh DB \".\" \"chain_2q_demo\"
End

Body 1
  Target Bodies(1) = $ vacuum
  Material = 1
End

Body 2
  Target Bodies(1) = $ substrate_layer3
  Material = 2
End

Material 1
  Name = \"Vacuum\"
  Relative Permittivity = 1.0
End

Material 2
  Name = \"Silicon\"
  Relative Permittivity = 11.45
End

Boundary Condition 1
  Target Boundaries(1) = $ gnd_layer1
  Potential = 0.0
End
'''
print(sif_snippet)
print(\"^ 上面的 $ name 直接对应 result.physical_groups 的 key\")
print(\"  Elmer 用 ElmerGrid 把 .msh 转成 ElmerSolver 能读的格式后即可跑\")
"""))

CELLS.append(md("""
## 8. 加一个 lumped port — 让 mesh 真的"能算 S 参"

chain_2q_native 自己 4 个 pin 都已被 netlist 连接, 没 open pin, 所以没有
自动端口。要做 S-parameter 仿真至少得有 1 个激励端口。这里通过 `options=`
kwarg 临时给 Q1.bus 加一个 lumped port, 重跑一次 build_mesh。
"""))

CELLS.append(code("""
# 临时把 Q1.bus 改成 lumped port — 实际项目里建议直接写进 YAML simulation.gmsh.ports
mesh_out2 = _REPO / "examples" / "dsl" / "outputs" / "chain_2q_with_port.msh"

# 注意 build_mesh options 会跑 _normalize_options shallow merge, 所以这里
# 需要把整段 ports 列表都给出来 (与 chain_2q 的 layer_stack 共存)。
result2 = build_mesh(
    yaml_path,
    output_path=mesh_out2,
    options={
        "mesh": demo_mesh,
        "ports": [
            {"pin": "Q1.bus", "type": "lumped", "impedance": 50.0},
        ],
    },
)

print("with-port physical groups:")
port_groups = {n: v for n, v in result2.physical_groups.items() if "port" in n}
for name, (dim, tags) in sorted(port_groups.items()):
    print(f"  dim={dim}  n_tags={len(tags)}  {name}")

if not port_groups:
    print("  (无 port group — Q1.bus 已被 netlist 连接, 无法当 open lumped port)")
    print("  → 把 chain_2q 改造成单 qubit 或断开 Q1↔bus 才能演示端口")
"""))

CELLS.append(md("""
## 9. 在 Gmsh GUI 里直观查看

最直观的"验证几何真的在 Gmsh 里"的方法 — 打开 GUI:

**方法 A: 重跑 build_mesh 时 show_gui=True**

```python
result = build_mesh(yaml_path, output_path=mesh_out,
                    options={"mesh": demo_mesh}, show_gui=True)
# Gmsh FLTK 窗口会弹出来, 可以转视角 / 打开 mesh / 看 physical groups
```

**方法 B: 用 gmsh CLI 直接打开 .msh**

```bash
gmsh examples/dsl/outputs/chain_2q_demo.msh
```

**方法 C: 命令行脚本**

```bash
C:\\ProgramData\\anaconda3\\envs\\metal-env\\python.exe \\
    examples\\dsl\\run_chain_gmsh_demo.py --gui
```

在 GUI 里看 `Tools → Visibility → Physical groups`, 能逐个切换 substrate /
ground / vacuum / port 可见性, 这就是下游求解器看到的东西。
"""))

CELLS.append(md("""
## 10. 收尾 — 释放 gmsh

当前 notebook 多次调用 build_mesh, gmsh 仍处于初始化态。如果还要再做
独立实验, 建议手动 finalize (build_mesh 自身的 finally 块只在 *它* 第一次
init 时调 finalize, 避免破坏 caller 的 session)。
"""))

CELLS.append(code("""
import gmsh
if gmsh.isInitialized():
    gmsh.finalize()
    print(\"gmsh 已 finalize, 下次 build_mesh 会重新初始化。\")
else:
    print(\"gmsh 已是未初始化态\")
"""))


notebook = {
    "cells": CELLS,
    "metadata": {
        "kernelspec": {
            "display_name": "metal-env",
            "language": "python",
            "name": "metal-env",
        },
        "language_info": {
            "name": "python",
            "version": "3.12",
        },
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}


OUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {OUT}  ({OUT.stat().st_size} bytes, {len(CELLS)} cells)")
