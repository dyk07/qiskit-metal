# DSL v3 示例

这个目录演示 Qiskit Metal 的 native YAML DSL（v3）。

核心流程很简单：写一个 `.metal.yaml` 文件描述芯片设计，调用 `build_ir()` 解析成中间表示，
再用 `build_design()` 导出到标准的 Metal `QDesign`。导出结果和手写 Python 构建的 QDesign
完全一样——qgeometry、pins、net_info 都在原来的位置。

## 从哪开始

打开 notebook 跑一遍最快：

1. **`primitive_native_demo.ipynb`** — 手写几何。每个 pad、junction、bus 都是显式的 primitive。适合理解 DSL 的基本结构。
2. **`transmon_pocket_demo.ipynb`** — 组件模板。写 `type: transmon_pocket` 就自动生成完整几何和 pin。适合理解模板系统。

如果想先看 YAML 不跑代码，从 `native_2q_minimal.metal.yaml` 开始——最短，结构最清晰。

## 文件一览

| 文件 | 说明 |
|------|------|
| `native_2q_minimal.metal.yaml` | 最小示例：两个 qubit，手写 primitive，一条连接 |
| `chain_2q_native.metal.yaml` | 完整示例：Q1 + Q2 + bus，带 `$extend` 模板复用 |
| `transmon_pocket_2q.metal.yaml` | 模板示例：`type: transmon_pocket` 自动生成几何 |
| `primitive_native_demo.ipynb` | Notebook：primitive-native 构建流程 |
| `transmon_pocket_demo.ipynb` | Notebook：模板构建流程 |
| `run_chain_demo.py` | 命令行脚本，兼 smoke test |
| `run_transmon_pocket_demo.py` | 命令行脚本，兼 smoke test |
| `.note/` | 开发笔记，不影响运行 |

## 运行

Notebook 启动时会自动把 `../../src` 加入 `sys.path`，不需要 pip install。
用 metal-env 的 kernel 打开就行。

命令行脚本从 worktree 根目录跑：

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

## 两种写法

**Primitive-native**——手写每个几何元素，灵活但啰嗦：

```yaml
Q1:
  primitives:
    - {name: pad, type: poly.rectangle, center: [0mm, 0mm], size: [420um, 90um]}
  pins:
    - {name: bus, points: [[0.34mm, -6um], [0.34mm, 6um]], width: 12um}
```

**组件模板**——写 type 和 options，模板生成所有几何和 pin：

```yaml
Q1:
  type: transmon_pocket
  options:
    pos_x: -1.2mm
    connection_pads:
      readout: {loc_W: 1, loc_H: 1}
```

两种都不用 qlibrary 的 Python class（不写 `class: TransmonPocket`），
导出结果都是标准 Metal `QDesign`。
