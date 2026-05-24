# DSL v3 / YAML-native TransmonPocket 现场演示 Checklist

目标 worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

## 0. 开场定位

- [ ] 说明最近 8 次 commit 合并来看是一项 DSL v3 native build target 工作。
- [ ] 一句话结论: YAML 先编译成 IR，再导出到 Metal `QDesign`; DSL 不再 build qlibrary Python `TransmonPocket`，而是 build YAML-native template 生成的 primitive/pin IR。
- [ ] 强调: 没有删除 Metal core，也不是删除 qlibrary 源码。

## 1. 环境检查

```powershell
cd D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main
git status --short --branch
git log --oneline -8
```

预期:

```text
## full_chain...origin/full_chain
```

## 2. Primitive Full Chain

打开:

- [ ] `examples/dsl/chain_2q_native.metal.yaml`
- [ ] `examples/dsl/run_chain_demo.py`
- [ ] `src/qiskit_metal/toolbox_metal/dsl/builder.py`

讲:

- [ ] YAML 同时有 `hamiltonian`、`circuit`、`netlist`、`geometry`。
- [ ] `build_ir()` 生成 `DesignIR`。
- [ ] `build_design()` 导出 qgeometry、pins、net_info、metadata。

运行:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

预期重点:

```text
components   : ['Q1', 'Q2', 'bus']
poly rows    : 6
path rows    : 2
junction rows: 2
net rows     : 4
PASS: native DSL chain exported to Metal
```

## 3. YAML-native TransmonPocket

打开:

- [ ] `examples/dsl/transmon_pocket_2q.metal.yaml`
- [ ] `examples/dsl/run_transmon_pocket_demo.py`
- [ ] `src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml`
- [ ] `src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml`
- [ ] `src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml`

讲:

- [ ] 用户写 `type: transmon_pocket`，不是 `class: TransmonPocket`。
- [ ] 继承链是 `qcomponent -> base_qubit -> transmon_pocket`。
- [ ] `connection_pads.readout` 由 generator 生成 geometry 和 pin。

运行:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

预期重点:

```text
components   : ['Q1', 'Q2']
types        : {'Q1': 'transmon_pocket', 'Q2': 'transmon_pocket'}
templates    : ... ['qcomponent', 'base_qubit', 'transmon_pocket'] ...
poly rows    : 8 ...
path rows    : 4 ...
junction rows: 2 ...
pins         : {'Q1': ['readout'], 'Q2': ['readout']}
net rows     : 2
PASS: YAML-native TransmonPocket template exported to Metal
```

## 4. Parity Tests

打开:

- [ ] `tests/test_design_dsl.py`
- [ ] `tests/test_design_dsl_templates.py`
- [ ] `tests/test_design_dsl_transmon_pocket.py`

讲:

- [ ] `tests/test_design_dsl_transmon_pocket.py` 用 qlibrary `TransmonPocket` 作为参考 oracle。
- [ ] 正常 DSL build 的组件类是 `NativeComponent`。
- [ ] parity 覆盖 geometry row、pin points/middle/normal/tangent/width/gap。

运行:

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py tests/test_design_dsl_transmon_pocket.py -q
```

预期:

```text
121 passed, 8 warnings
```

## 5. 必答问题短句

- [ ] qlibrary 是否删除了?

没有。Metal core 和 qlibrary 源码仍然存在; DSL v3 只是移除了 qlibrary Python class 作为 authoring/build target。

- [ ] 默认值如何来?

`qcomponent`、`base_qubit`、`transmon_pocket` parent-first 合并，然后实例 `options` 覆盖。`connection_pads` 每个 entry 继承 `_default_connection_pads`。

- [ ] pin 和 netlist 写到哪里?

pin 写到 `design.components[name].pins`; netlist 通过 `design.connect_pins()` 写到 `design.net_info`; 全链路快照写到 `design.metadata["dsl_chain"]`。

- [ ] 为什么说 full chain?

因为 `vars/circuit/hamiltonian/netlist/geometry` 都在 `build_ir()` 中分层解析，geometry 导出后又把 derived bounds、pin、netlist 信息写回 metadata。

## 6. 收尾结论

- [ ] Primitive v3 chain 已能导出 Metal qgeometry/pin/netlist。
- [ ] YAML-native `transmon_pocket` 已能生成 static pocket geometry 和 generated connection pads。
- [ ] Parity tests 已验证与原 qlibrary TransmonPocket 参考实现一致。
- [ ] 剩余工作是 future enhancement/cleanup，不是当前 TransmonPocket parity blocker。

