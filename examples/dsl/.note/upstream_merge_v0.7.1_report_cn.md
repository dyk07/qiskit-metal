# 上游合并报告:v0.6.2 → v0.7.1(56 commits,2026‑05‑21 ~ 05‑22)

> 合并提交:`9b9b6399`(本地 full_chain 分支)
> 起点:`b8222e1e Merge upstream qiskit-community/main into full_chain (v0.5.3.post1 -> v0.6.2)`
> 终点:`9ce7b666 Merge pull request #1088 from qiskit-community/chore/cleanup-tracked-junk`
> 上游版本号:`0.6.2 → 0.7.1`

## 合并过程

- **冲突**:仅 `CLAUDE.md` 一处,按用户约定全部采用本地 HEAD(worktree 专属说明,不与上游内容混合)。已写入记忆,以后所有合并都走相同处理。
- **本地未提交改动**:`examples/dsl/.note/` 下的未跟踪文件和 walkthrough 笔记的本地编辑在合并前 stash,合并后已 pop 恢复。
- **DSL 全部产物完好**:`src/qiskit_metal/toolbox_metal/dsl/*`、`dsl_templates/*`、`tests/test_design_dsl*.py`、`examples/dsl/**` 均未被上游触碰(上游 diff 显示为"删除"只是因为这些文件不在上游)。
- **合并后烟雾测试**(metal-env):
  - `examples/dsl/run_transmon_pocket_demo.py` → **PASS**(8 poly / 4 path / 2 junction / 2 pin)
  - `examples/dsl/run_chain_demo.py` → **PASS**(Q1/Q2/bus 三组件,4 net)
  - `from qiskit_metal.toolbox_metal.dsl import build_ir, build_design` 正常,模块加载路径 = worktree `src/`。

---

## 一、与 DSL 直接相关的改动(重点说明)

### 1. v0.7.0 lite‑by‑default —— `pyproject.toml` 依赖大重排

**这是这一轮合并里 DSL 最需要关注的一处。**

| 依赖 | 原本(v0.6.2 base) | 现在(v0.7.0+ base) | 现在所属 extra |
|------|---------------------|------------------------|----------------|
| `pyside6` | base | **移出** | `[gui]` |
| `qdarkstyle` | base | **移出** | `[gui]` |
| `pyaedt` | base | **移出** | `[ansys]` |
| `pyEPR-quantum` | base | **移出** | `[ansys]` |
| `gmsh` | base | **移出** | `[mesh]`(`[fem]` 是别名) |

新增 extras:`[gui]` / `[ansys]` / `[mesh]` / `[fem]`(= `[mesh]`) / `[full]`(= 旧 v0.6.x 全家桶)。

**对 DSL 的影响**:
- `dsl/` 包本身**不 import 上述任何重依赖**——只用到了 `yaml`、`shapely`、`sympy`(经 `parsing.parse_value`)、stdlib。所以 **`build_ir()` 在 lite 安装下完全可用**。
- `build_design()` 调用 `QDesign` 写 qgeometry 表 / 调 `connect_pins`,**也不触发 Qt 或 pyaedt**——`DesignPlanar` 本身是纯 Python 的。这条路径在 lite 下也可用。
- **会受影响的下游路径**:
  - `from qiskit_metal import MetalGUI` —— 需要 `[gui]` 才能装上 PySide6。
  - DSL → GDS 导出 —— `gdstk` 在 base 里,**不受影响**。
  - DSL → Ansys / pyEPR —— 需 `[ansys]`。
  - DSL → Gmsh / Elmer FEM —— 需 `[mesh]`。
- **worktree 当前用的 `metal-env` conda 环境** 是按 `[full]` 配置的(`environment.yml` 里 PySide6 / scqubits / geopandas / pyEPR‑quantum 都在),**不受 lite flip 影响**,所有 DSL demo 仍直接可跑。
- **对 README / 文档 / 用户**:如果以后 DSL 写文档时建议安装命令,**不能再写 `pip install quantum-metal`**——要明确写 `pip install "quantum-metal[full]"` 才能拿到 v0.6.x 旧体验;否则只是 lite 装,GUI 不会有。

### 2. `qiskit_metal` → `quantum_metal` 导入路径重命名预警

`src/qiskit_metal/__init__.py` 把原本的 lite‑flip 警告替换成了**导入路径重命名警告**(`_maybe_warn_import_rename`):

> 未来一个大版本(v0.8 或 v1.0)会把 Python 导入路径从 `qiskit_metal` 改成 `quantum_metal`。

**对 DSL 的影响**:
- **现在**仅是 `FutureWarning`,不阻塞任何东西(可以用环境变量 `QISKIT_METAL_SUPPRESS_RENAME_WARNING=1` 关闭——我们的 demo script 已经在做)。
- **将来**需要把 DSL 内部所有 `from qiskit_metal.* import ...` 全部改成 `from quantum_metal.* import ...`。当前 DSL 涉及的 import:
  - `dsl/builder.py`、`dsl/component_templates.py`、`dsl/geometry_ops.py`、`dsl/_helpers.py`、`dsl/expression.py`、`dsl/template_*.py` 都从 `qiskit_metal.toolbox_metal.parsing`、`qiskit_metal.draw`、`qiskit_metal.qgeometries` 等导入。
  - `examples/dsl/*.metal.yaml` 文件本身不涉及——只有 demo Python / notebook 需要改。
- **不需要现在改**,等上游真正切到 `quantum_metal` 包名再批量替换。但可以在 DSL 设计文档里加一条迁移备忘。

### 3. `qm.view(design)` 已在 v0.6.1 完成 Qt 解耦

之前看 design 必须靠 `MetalGUI`(PySide6)。现在 `from qiskit_metal.viewer import view` 是 headless 的 matplotlib 渲染入口。

**对 DSL 的影响**:
- DSL → `QDesign` 之后想"看一眼版图",可以走 `qm.view(design)`,**完全不依赖 Qt**——很适合放进 `run_*_demo.py` 和 notebook,在 lite 安装的环境里也能跑。
- **可选优化**:`examples/dsl/run_transmon_pocket_demo.py` 目前只是 print metadata,可以追加一个 `qm.view(design)` 的渲染步骤当作可视化烟雾测试。

### 4. 新增 / 调整的 analyses(可能将来供 DSL `hamiltonian:` 段用到)

- `src/qiskit_metal/analyses/__init__.py` 新增 ~65 行 —— 主要是 New LOM 相关:`docs/tut/4-Analysis/4.04-New-LOM-and-Fluxonium-Example.ipynb`、`4.05-New-LOM-and-Two-Coupled-Transmon-Example*.ipynb`。
- `analyses/hamiltonian/transmon_charge_basis.py` 有小幅改动。

**对 DSL 的影响**:
- 目前 DSL 的 `hamiltonian:` 段只是 metadata,**还没有真正接到 analyses 层**(`builder.py` 把 hamiltonian 段塞进 `DesignIR.hamiltonian`、原样存,不调度计算)。
- 等以后想做"DSL 一键算谱"时,**New LOM(`analyses.lom.*`)是首选接入点**,而不是旧 LOM。可在新增 `analyses_pipeline` 段的设计文档里直接引用。

### 5. GDS 渲染器:多了 legend 功能 + 14 个新测试

`renderers/renderer_gds/gds_renderer.py` +310 行;新增 `tests/test_gds_export.py`。同步出现的 tutorial:`docs/tut/3-Renderers/3.2-Export-your-design-to-GDS.ipynb`(暴增 19k 行,主要是输出 cell)。

**对 DSL 的影响**:DSL → GDS 路径将来若做导出脚本,可以直接利用 GDS legend 功能(把每层 GDS layer 的图例画出来),不需要 DSL 自己实现。

### 6. 其它源码改动(对 DSL 影响微乎其微,只记一笔)

- `qlibrary/core/qroute.py`、`designs/design_base.py` 各 1~2 行,签名未变。
- `renderers/renderer_elmer/elmer_runner.py` +111 行(unpinning Elmer 9.0、友好错误信息),DSL 不直接调。
- `renderers/renderer_mpl/*`、`_gui/main_window*.py` 改动都是 PySide6 docstring + 小错误处理,DSL 用不到。
- `toolbox_metal/import_export.py`:diff 显示有变化,但与上次合并(`b8222e1e`)对比是一致的,本次没有再修改——**没有冲突**。

---

## 二、与 DSL 无关的改动(简写)

> 一句话定性,不展开。

### 文档 / 教程(本次大头)
- **README + ROADMAP + docs**:整体改成 v0.7.0 风格(lite‑first、Colab badge、CITATION.cff、Hero GIF)。
- **新增 11 个 tutorial notebook**:`1.4 headless quick view`、`1.5 parametric design`、`1.6 QComponent shape library`、`3.5 Gmsh renderer`、`4.04/4.05 New LOM 系列`、`4.16-4.19`(S21 fit / port resonator / ElmerFEM / etc.)、`cross-resonance gate`、`Jaynes-Cummings`。
- **双 tutorial 文件夹**:`tutorials/`(空格命名)和 `docs/tut/`(连字符命名)**全套 54 对** 同步过一遍,加 CI gate `scripts/check_tutorials_sync.py`。**和 DSL 没关系,但合并后我们的 `docs/tut/` 多了新 notebook,以后改任何 tutorial 都要双写。**
- Sphinx docs build:`~1500 个 warning → 0`,`docs-ci` 加了 mock imports。

### CI / 工具链
- pre-commit 从 `yapf` 切到 `ruff`,新加 `pre-push` 钩子(`hooks/pre-push`)。
- CI matrix:Python 3.10 / 3.11 / 3.12 × {ubuntu-24.04, macos-15, windows-2025},基本同前。
- ruff 0.15.14 兼容性修复,`_dev/` 目录排除在 ruff 范围外。

### 仓库清理
- 0895a8ae:untrack 73 个 tutorial 输出产物(PNG / 中间数据),加 gitignore patterns。
- 删除 `README_Gmsh_Elmer.md` → 新增 `README_Open_FEM_Stack.md`(open‑FEM 站位重命名)。
- 新增 `_dev/` 一大批脚本(`jupyter_gui/` 原型 + `sync_two_folders.py` + notebook 标题修复脚本),纯开发工具,**和 DSL 无关**。
- `CITATION.cff` 新加。

### 版本号
- `pyproject.toml` version: `0.6.2 → 0.7.1`(中间经过 0.7.0)。
- `src/qiskit_metal/__init__.py` 里的 lite‑flip 警告函数被换成 rename 警告函数(见第一节)。

---

## 三、需要后续跟进的 TODO(给未来的 DSL 工作)

1. **lite‑safe 校验**:在 `tests/test_design_dsl*.py` 里加一条 lite 模式断言——确保不靠 Qt / pyaedt / gmsh 也能 `build_ir()` 跑通(目前隐式成立,但没有显式 gate)。
2. **import 路径迁移备忘**:在 `examples/dsl/.note/` 或 builder 顶部加注释,提醒未来 `qiskit_metal` → `quantum_metal` 重命名时需要批量替换。
3. **DSL demo 加 `qm.view()`**:`run_*_demo.py` 末尾追加 headless 渲染调用,既验证 lite 路径,也给后续 notebook 模板做参考。
4. **New LOM 接入点**:`hamiltonian:` 段未来要走 `analyses.lom.*` 而不是 legacy LOM——在 DSL v4 设计稿里点一笔。
5. **环境一致性**:`scripts/check_env_consistency.py` 现在校验 `environment.yml` 和 `pyproject.toml` 一致——如果 DSL 增加任何运行时新依赖,两边都得改。

---

## 四、合并风险评估

| 项目 | 状态 |
|------|------|
| DSL 代码完整性 | ✅ 全部保留,无冲突 |
| DSL demo 可跑性 | ✅ `run_transmon_pocket_demo.py` / `run_chain_demo.py` 都 PASS |
| DSL 测试可跑性 | ⚠️ 未在本次合并后跑 `tox -e py3.12 -- tests/test_design_dsl.py`(metal-env 是 conda 不是 tox 管理的);建议手工跑一遍 |
| CLAUDE.md 一致性 | ✅ 保留本地,未污染 |
| 后续 push 风险 | ⚠️ `origin/full_chain` 落后本地 58 commits,push 前确认 fork 没人在改 |

测试建议:
```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -x
```
