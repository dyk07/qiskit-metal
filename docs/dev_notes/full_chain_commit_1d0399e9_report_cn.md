# full_chain 最新提交（1d0399e9, `dsl v3-0`）详细代码说明（用于汇报）

## 0. 提交概览

- 分支：`full_chain`
- 最新提交：`1d0399e9`
- 提交信息：`dsl v3-0`
- 改动规模：6 个文件，约 1404 行新增（`design_dsl.py` 为主体）

本次提交的核心目标是：
**引入一个“原生几何优先（native geometry）”的 v3 YAML DSL 链路**，将设计过程拆成两步：
1. `build_ir()`：先把 YAML 解析为中间表示（IR）
2. `export_ir_to_metal()` / `build_design()`：再把 IR 导出为可用的 Metal `QDesign`

这意味着 DSL 不再直接依赖 `TransmonPocket`、`RouteMeander` 这类 qlibrary 组件，而是直接描述 primitive（`poly/path/junction`）并显式定义 pin 与 netlist。

---

## 1. 本次提交改了什么（按文件）

### 1.1 `src/qiskit_metal/toolbox_metal/design_dsl.py`

新增完整 DSL 引擎，包括：

- 领域数据模型（`PrimitiveIR`、`PinIR`、`ComponentIR`、`DesignIR`）
- YAML 加载与错误封装（路径/文本双输入）
- 插值系统（`${...}`）
- 宏能力（`$include`、`$extend`、`$for`）
- primitive 构造与几何变换（平移、旋转、原点）
- 导出到 Metal（`add_qgeometry`、`add_pin`、`connect_pins`）
- 衍生信息 `derived` 计算（bounds、length、pin middle、连接规范化）

### 1.2 `examples/dsl/chain_2q_native.metal.yaml`

提供“哈密顿量→电路→网表→几何”全链路示例：

- `hamiltonian` 引用 `circuit` 的参数
- `geometry` 引用 `circuit/vars`
- `templates` + `$extend` 复用 Q1/Q2 模板
- bus 组件独立建模并通过 netlist 连接 Q1/Q2

### 1.3 `examples/dsl/native_2q_minimal.metal.yaml`

最小可运行样例，用于快速 smoke test 与教学起步。

### 1.4 `examples/dsl/run_chain_demo.py`

提供脚本化验证入口：

- 调用 `build_ir()` + `build_design()`
- 打印 qgeometry / net 信息
- 用断言验证基本正确性

### 1.5 `tests/test_design_dsl.py`

新增 DSL 端到端测试与异常路径测试：

- 插值正确性
- primitive 类型支持
- include/template/loop 展开
- override 重算
- legacy 形态拒绝
- netlist 引用错误拒绝

### 1.6 `examples/dsl/README.md`

补充 DSL v3 设计理念、API、支持语法与数据流说明。

---

## 2. 核心设计思路（架构层）

### 2.1 两阶段流水线

**阶段 A：解析与归一化（`build_ir`）**

- 输入：YAML 路径或 YAML 字符串
- 输出：`DesignIR`
- 主要职责：
  - schema 校验
  - 插值解析
  - 模板/循环展开
  - primitive/pin 解析为数值几何
  - netlist 结构标准化
  - 生成 `derived`

**阶段 B：导出与落地（`export_ir_to_metal`）**

- 输入：`DesignIR`
- 输出：标准 `QDesign`
- 主要职责：
  - 实例化 design（默认 `DesignPlanar`）
  - 为每个 component 建立轻量 `NativeComponent`
  - primitive 写入 `qgeometry` 表
  - pin 写入组件
  - 按 netlist 调用 `connect_pins`
  - 把 DSL 全链路快照挂到 `design.metadata["dsl_chain"]`

### 2.2 为什么是“先 IR 后导出”

这个拆分非常关键，主要收益：

1. **可解释性提升**：IR 可以单独检查，不必先进入 GUI/renderer。
2. **测试粒度更细**：可先测 parser 与几何，再测导出。
3. **扩展性更好**：未来可增加新导出后端（例如只导出几何/JSON）。
4. **更易做审计与追踪**：`metadata["dsl_chain"]` 保留解析后全链路状态。

---

## 3. 代码执行路径（汇报可直接讲）

建议你按这条“单一路径”讲，不会发散：

`build_design(source)`
→ `build_ir(source)`
→ `_load_yaml` / `_expand_includes`
→ schema 检查
→ `_walk_substitute`（vars/circuit/hamiltonian/netlist 分层插值）
→ `_parse_components`（模板展开 + primitive/pin 解析）
→ `_derive`
→ `export_ir_to_metal`
→ `_instantiate_design`
→ `NativeComponent + add_qgeometry + add_pin`
→ `connect_pins`
→ `design.metadata["dsl_chain"]`

### 3.1 解析阶段关键点

- `schema` 必须严格等于 `qiskit-metal/design-dsl/3`
- 上下文 `ctx` 构造顺序体现“依赖方向”：
  - `vars` 先
  - `circuit` 依赖 `vars`
  - `hamiltonian` 依赖 `vars + circuit`
  - `netlist` 依赖 `vars + circuit + hamiltonian`
- `geometry` 在上述上下文下再次插值，确保几何参数可引用电路参数

### 3.2 展开机制关键点

- `$include`：仅允许“单键对象 `{ $include: path }`”
- `$extend`：模板继承，支持链式继承并检测循环
- `$for`：列表驱动批量展开，逐项把迭代变量合入上下文

### 3.3 primitive 解析关键点

支持类型：

- `poly.rectangle`
- `poly.polygon`
- `path.line` / `path.polyline`
- `junction.line`

数值解析通过 `parse_value`，因此 `420um`、`1.2mm`、字符串表达式插值后的单位字符串都可转成浮点。

### 3.4 导出阶段关键点

- `NativeComponent` 是最小承载体，不依赖 qlibrary 的 `make()` 逻辑。
- primitive 的 `width/fillet/option` 会被保留并透传给 `add_qgeometry`。
- netlist 连接前会校验组件名与 pin 名，避免 silent failure。
- 连接成功后回填 `net_id` 到 `derived.netlist.connections`。

---

## 4. 数据结构与存储位置（汇报高频问题）

### 4.1 `DesignIR`

字段包括：

- `schema`
- `vars`
- `hamiltonian`
- `circuit`
- `netlist`
- `design`
- `components`（`ComponentIR` 列表）
- `geometry`（metadata-safe）
- `derived`

### 4.2 导出后的 `QDesign` 中数据在哪

- 几何：`design.qgeometry.tables[...]`
- 引脚：`design.components[name].pins`
- 连接：`design.net_info`
- DSL 全链路快照：`design.metadata["dsl_chain"]`

这点非常适合向评审解释“可追踪性”。

---

## 5. 测试覆盖分析（你需要会讲“测了什么、没测什么”）

已覆盖（`tests/test_design_dsl.py`）：

1. **主链路正确性**：`build_ir` 能把 `circuit` 参数传到 geometry。
2. **导出正确性**：qgeometry 表、pins、netlist 行数符合预期。
3. **derived 正确性**：路径长度、pin 中点、连接结构。
4. **override 生效**：覆盖参数后几何尺寸重算。
5. **语法能力**：include/template/for/interpolation 协作。
6. **几何类型**：polygon、junction.line。
7. **负例**：
   - schema 错误
   - 混入 legacy qlibrary 组件
   - 使用 routes（v3 不允许）
   - netlist 引用不存在 pin

相对欠缺（可作为汇报中的“改进建议”）：

- 旋转 + 平移组合变换的数值精度回归测试
- 复杂 include 深层嵌套与错误路径提示细化
- 大规模组件（例如 100+）展开性能基准
- 导出后与 renderer 端到端一致性测试

---

## 6. 代码质量评估（针对“AI 生成代码如何评估”）

### 6.1 优点

1. **职责边界清晰**：解析、展开、构造、导出分层明确。
2. **错误信息质量较高**：多数异常都带上下文位置。
3. **扩展入口明确**：`register_design` 支持设计类注册。
4. **测试较完整**：正反路径都有。
5. **可观测性好**：`dsl_chain` 元数据方便调试与回放。

### 6.2 风险点

1. **表达式能力有限**：`${...}` 仅路径替换，不支持算术表达式；
   若 YAML 写 `"${bus_y} - 6um"`，是否总能被下游 `parse_value` 正确解释，要在真实运行环境确认。
2. **类型收敛策略较宽**：很多地方先转字符串再解析，出错时可能离源头较远。
3. **`_load_yaml` 的路径判断是启发式**：字符串短、无换行且“恰好存在同名文件”时会被当路径。
4. **`_deep_merge` 对列表策略是覆盖，不是按元素 merge**：对复杂 override 场景要有预期。
5. **导出阶段 pin 名校验重复计算**：`_component_pin_names` 在循环中调用，规模大时有优化空间（非功能 bug）。

### 6.3 维护性评价

整体维护性中上：

- 函数命名较语义化
- 工具函数拆分较细
- 但模块体量偏大（单文件 ~900 行），后续可考虑拆成
  - loader/interpolation
  - template expansion
  - geometry compiler
  - exporter

---

## 7. 汇报建议（你如何讲得“像在评审代码”）

你可以按下面 6 分钟结构：

1. **问题定义（1 分钟）**
   - 旧方式依赖 qlibrary 组件实例化
   - 本提交改为 native primitive + 显式 pin/netlist
2. **架构方案（1 分钟）**
   - 两阶段：`build_ir` 与 `export_ir_to_metal`
3. **执行路径（1.5 分钟）**
   - 从 YAML 到 `design.metadata["dsl_chain"]`
4. **示例讲解（1 分钟）**
   - `chain_2q_native.metal.yaml` 中 template/extend/连接
5. **质量评估（1 分钟）**
   - 优点 + 风险点
6. **改进计划（0.5 分钟）**
   - 性能基准、表达式能力、模块拆分

---

## 8. 第一轮结论（可直接用于汇报总结页）

本提交不是“加一个示例”这么简单，而是引入了 **v3 DSL 的完整执行内核**：

- 语义上：把 Hamiltonian/Circuit/Netlist/Geometry 链路连接起来
- 实现上：把“解析”和“导出”解耦
- 工程上：补充了样例、文档、测试

它的价值在于把 DSL 从“脚本糖衣”提升成了“可测试、可追踪、可扩展”的基础设施。


====================
第二轮补充（评估与答辩增强）
====================

## 9. 深入补充 A：把关键函数映射到“职责清单”

- `build_ir()`：总控编译器（YAML -> 解析 -> 展开 -> IR）
- `_expand_includes()`：文件级复用
- `_expand_node()`：模板与循环语法的核心展开器
- `_make_primitive_geometry()`：语法到 shapely 几何的最小闭环
- `_derive()`：构建上行衍生信息，连接设计分析视角
- `export_ir_to_metal()`：IR 到 Metal 对象图的落地器
- `build_design()`：一键端到端入口

你在答辩时可以这样说：
“这套代码本质上是一个小型编译器：前端负责语法和替换，后端负责导出到 Metal 运行时对象。”

## 10. 深入补充 B：可量化评估指标（适合评审问‘怎么判定好坏’）

建议你给出 5 类 KPI：

1. **正确性**
   - 单元测试通过率
   - 示例文件是否可稳定生成同样的 qgeometry 行数
2. **鲁棒性**
   - 错误输入是否抛出可定位异常
   - netlist 异常是否能提前失败
3. **可维护性**
   - 新增 primitive 类型的改动行数（越少越好）
   - 模块耦合度（是否能拆文件）
4. **可扩展性**
   - 是否支持新 Design 类注册
   - 是否可追加新导出后端
5. **性能**
   - 组件数量 N 增长时 `build_ir` 的时间曲线

## 11. 深入补充 C：面向 AI 生成代码的“审查清单”

你可以直接把这份清单带到汇报现场：

1. **需求一致性**：代码是否严格实现 v3 native 的边界（不混入 qlibrary class）
2. **失败模式**：异常是否可读且尽量早失败
3. **隐式假设**：单位解析、字符串表达式、路径判定是否有歧义
4. **回归保护**：是否有关键正反测试
5. **可观测性**：是否提供足够调试信息（`dsl_chain`）
6. **可演进性**：新 primitive、新 transform、新 schema 的改动路径是否清晰

## 12. 深入补充 D：你可能会被问到的 8 个问题（附回答要点）

1. **为什么不继续直接实例化 qlibrary 组件？**
   - 因为 native primitive 更统一、可控、可测试，避免 qlibrary 行为差异影响 DSL 语义。

2. **IR 是否只是中间过渡，价值在哪？**
   - IR 提供可检查快照，支持独立测试、调试、后续多后端导出。

3. **模板系统会不会过于复杂？**
   - 目前只支持 `$include/$extend/$for`，功能受控，且有循环检测。

4. **表达式支持到什么程度？**
   - 当前是路径插值 + 单位解析，不是通用表达式引擎。

5. **如果连接的 pin 不存在会怎样？**
   - 在导出连接前显式校验并抛错，不会 silent fail。

6. **如何保证 geometry 和 netlist 一致？**
   - pin 来源于同一组件定义，连接前做 component/pin 名称校验。

7. **这次提交最值得肯定的一点是什么？**
   - 从“脚本功能”升级到“工程化链路”：示例、测试、文档、元数据追踪一体化。

8. **下一步最优先做什么？**
   - 做性能与数值稳定性回归基准；补旋转/复杂表达式边界测试。

## 13. 深入补充 E：可执行改进路线（如果导师问 Roadmap）

短期（1~2 周）：
- 增加 transform 组合边界测试
- 增加 include 路径错误信息的上下文
- 跑一组 10/50/100 组件的 `build_ir` 基准

中期（1~2 月）：
- 把 `design_dsl.py` 拆分成 3~4 个模块
- 增加 primitive 扩展插件机制（注册表）
- 完善 schema 文档与自动校验

长期：
- 引入多后端导出（不仅 Metal runtime）
- 建立 DSL 版本迁移工具（v3 -> v4）

---

## 14. 第二轮结论（补充后）

你可以把这次提交定义为：

> “一次针对设计 DSL 的基础设施升级：以 IR 为核心，把参数链路、几何编译、导出落地和测试验证闭环打通。”

从评审角度，它已经具备“可用 + 可测 + 可讲清”的条件；
从工程演进角度，下一步重点是“模块化与边界回归”。
