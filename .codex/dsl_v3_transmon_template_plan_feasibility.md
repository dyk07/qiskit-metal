# DSL v3 TransmonPocket Template Plan Feasibility

Date: 2026-05-11

Target worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Evaluated plan:

- Split the oversized `src/qiskit_metal/toolbox_metal/design_dsl.py`.
- Move the in-progress "replace qiskit template functionality" work out of that file.
- First focus on a YAML-native replacement for `TransmonPocket`.
- Cover the `TransmonPocket -> BaseQubit -> QComponent` behavior chain.
- Do not hardcode the component in Python; implement the component recipe in YAML.
- If the goal is too large, keep `QComponent`.

Files inspected lightly:

- `src/qiskit_metal/toolbox_metal/design_dsl.py`
- `tests/test_design_dsl.py`
- `examples/dsl/README.md`
- `examples/dsl/chain_2q_native.metal.yaml`
- `src/qiskit_metal/qlibrary/qubits/transmon_pocket.py`
- `src/qiskit_metal/qlibrary/core/qubit.py`
- `src/qiskit_metal/qlibrary/core/base.py`
- `src/qiskit_metal/draw/basic.py`
- `src/qiskit_metal/toolbox_metal/parsing.py`
- `pyproject.toml`

No core code was modified for this evaluation.

## Short Verdict

The plan is directionally correct but too large if interpreted as "make the first implementation step a complete `TransmonPocket` replacement." It is feasible only if split into staged, testable slices.

Feasible immediately:

- Split `design_dsl.py` into a package without behavior changes.
- Keep `design_dsl.py` as a public compatibility facade.
- Add a generic YAML component-template resolver above the current primitive IR.
- Keep `QDesign`, `QComponent`, `NativeComponent`, qgeometry, pins, and net_info.
- Express `QComponent`, `BaseQubit`, and `TransmonPocket` defaults/recipes in YAML templates.

Not feasible as a single first step:

- Full `TransmonPocket` parity, including `BaseQubit` connection-pad inheritance, connector path generation, buffer/subtract path, `rotate_position`, and `add_pin(input_as_norm=True)` semantics.
- Full replacement of the Python qlibrary implementation with no intermediate generic helper layer.
- Reimplementing actual `QComponent` lifecycle in YAML.

Recommended interpretation:

> Keep `QComponent` as the Metal integration layer. Replace qlibrary component authoring/build targets with YAML-native templates that expand into the existing primitive/pin IR.

The Python side may provide generic operations such as `rectangle`, `polyline`, `buffer`, `scale`, `translate`, `rotate_position`, and `pin_from_path_end`. What must not happen is a Python function named or shaped like `make_transmon_pocket()` that encodes the component recipe. The recipe belongs in YAML.

## Feasibility Matrix

| Plan Item | Feasibility | Judgment |
| --- | --- | --- |
| Split `design_dsl.py` | High | Safe if behavior-preserving and tests stay compatible. |
| Preserve `design_dsl.py` public API | High | Should be mandatory. Existing tests/examples import it. |
| Move template replacement work out of `design_dsl.py` | High | Correct architectural move. |
| Add `type + options` component templates | High | Needed next layer above current primitive IR. |
| Implement template inheritance in YAML | Medium | Feasible, but should start with shallow/default inheritance and explicit merge rules. |
| Model `QComponent` in YAML | Medium | Feasible for defaults/metadata only, not lifecycle. |
| Model `BaseQubit` in YAML | Medium | Feasible if focused on `connection_pads` default inheritance. |
| Full YAML `TransmonPocket` static pocket geometry | Medium-High | Feasible with local options and numeric expressions. |
| Full YAML connection pad generation | Medium-Low | Requires map generators, geometry references, path helpers, buffer, transforms, and pin derivation. |
| Full qlibrary parity in first implementation | Low | Too much for one step; must be staged. |
| Remove qlibrary from repo | Low / Wrong now | Keep as reference and compatibility layer. |
| Avoid Python hardcoding | Feasible with constraints | Use generic operation registry, not component-specific Python. |

## What Current v3 Already Supports

Current `design_dsl.py` is about 1161 lines and mixes many responsibilities:

- schema constants
- error type
- IR dataclasses
- YAML loading and duplicate-key rejection
- `$include`
- `$extend`
- `$for`
- interpolation
- primitive parsing
- pin parsing
- transforms
- netlist normalization/validation
- derived metadata
- `DesignPlanar` instantiation
- `NativeComponent`
- export to qgeometry/pins/net_info
- `build_ir`
- `build_design`

The current primitive-native v3 already gives a good lower layer:

- root `hamiltonian`, `circuit`, `netlist`, `geometry`
- explicit primitives and pins
- primitive types:
  - `poly.rectangle`
  - `poly.polygon`
  - `path.line`
  - `path.polyline`
  - `junction.line`
- transforms:
  - translate
  - rotate
  - origin
- `NativeComponent` export to Metal qgeometry
- pin export through `component.add_pin`
- netlist export through `design.connect_pins`
- derived geometry summary in `ir.derived`

That lower layer should stay. The missing piece is a YAML-native component template expansion layer above it.

## What `TransmonPocket` Actually Requires

`TransmonPocket` is not only a few rectangles. Its behavior comes from three levels.

### QComponent Behavior

`QComponent` provides:

- default options:
  - `pos_x`
  - `pos_y`
  - `orientation`
  - `chip`
  - `layer`
- design registration and component id
- template option collection through class MRO
- option parsing through `self.p`
- pin storage
- metadata
- qgeometry table usage
- `add_qgeometry`
- `add_pin`
- rebuild lifecycle

For DSL v3, do not reimplement this lifecycle in YAML. Keep it in `NativeComponent` and the exporter. YAML should represent only reusable defaults, metadata, and geometry-generation recipe.

### BaseQubit Behavior

`BaseQubit` adds:

- `connection_pads`
- `_default_connection_pads`
- logic that deep-copies `_default_connection_pads` into every named connection pad
- per-pad override merge
- deletion of `_default_connection_pads` from final instance options

This is important and must be modeled. The YAML template engine needs a generic map-entry inheritance rule, for example:

```yaml
merge_rules:
  connection_pads:
    each_entry_extends: _default_connection_pads
    remove_after_resolve: [_default_connection_pads]
```

That rule is not `TransmonPocket`-specific and can live in the generic template resolver.

### TransmonPocket Behavior

`TransmonPocket.default_options` includes:

- `pad_gap`
- `inductor_width`
- `pad_width`
- `pad_height`
- `pocket_width`
- `pocket_height`
- `_default_connection_pads`:
  - `pad_gap`
  - `pad_width`
  - `pad_height`
  - `pad_cpw_shift`
  - `pad_cpw_extent`
  - `cpw_width`
  - `cpw_gap`
  - `cpw_extend`
  - `pocket_extent`
  - `pocket_rise`
  - `loc_W`
  - `loc_H`

`make_pocket()` creates:

- `pad_top`
- `pad_bot`
- `rect_pk` subtract pocket
- `rect_jj` junction line
- rotate by `orientation`
- translate by `pos_x`, `pos_y`

`make_connection_pad(name)` creates, for each connection pad:

- connector pad rectangle
- connector wire path with four points
- buffered connector wire helper/subtract polygon
- scale by `loc_W`, `loc_H`
- translate relative to transmon pad/pocket geometry
- `rotate_position` around component position
- qgeometry rows:
  - `{name}_connector_pad`
  - `{name}_wire`
  - `{name}_wire_sub`
- pin generated from the final path segment using `input_as_norm=True`

This means "complete `TransmonPocket`" requires more than current primitive lists. It requires:

- local option scope
- numeric expressions with units
- references to generated geometry or path points
- map generators over `connection_pads`
- generic geometry operations
- derived pin construction from path segments
- parity tests

## Core Feasibility Issue In The Proposed Plan

The proposed plan says "第一步就只聚焦于替代TransmonPocket的完整实现". The focus is good, but "第一步" and "完整实现" conflict.

A complete replacement depends on several new generic features that do not exist yet:

1. component `type + options`
2. YAML template loading
3. template inheritance
4. option schema/default merging
5. `connection_pads` map-entry default inheritance
6. local expression context
7. expression evaluation with units
8. geometry helper operations
9. generator loops over maps
10. geometry references between generated objects
11. pin helpers equivalent to `input_as_norm=True`
12. parity testing against the existing Python component

Trying to deliver all of that in one step is likely to create a large, hard-to-review patch and hidden component-specific Python shortcuts.

The feasible version is:

> First project milestone: YAML-native `TransmonPocket` parity.  
> First implementation step: behavior-preserving file split.  
> First functional step: generic template resolver plus a static pocket subset.

## Recommended Revised Plan

### Milestone 0: Test And Baseline Hygiene

Goal: make later refactors measurable.

Actions:

- Document the required test invocation for this worktree.
- Ensure the environment has project metadata and `pytest-rich`, for example through the repo's intended install workflow.
- Keep `tests/test_design_dsl.py` as the regression suite for the split.

Notes:

- In the current shell, `pytest tests/test_design_dsl.py -q` failed because `--rich` was configured but the active environment lacked the plugin.
- With `PYTHONPATH=src`, test collection still failed because `qiskit_metal.__init__` expected installed distribution metadata for `quantum-metal`.
- This looks like environment setup, not a DSL code assertion failure.

Acceptance:

- A repeatable command runs `tests/test_design_dsl.py`.

### Milestone 1: Split `design_dsl.py` Without Behavior Change

Goal: reduce file size and isolate responsibilities before adding template complexity.

Recommended package:

```text
src/qiskit_metal/toolbox_metal/design_dsl.py
src/qiskit_metal/toolbox_metal/dsl/
  __init__.py
  errors.py
  schema.py
  ir.py
  yaml_io.py
  expansion.py
  expression.py
  primitives.py
  pins.py
  netlist.py
  derive.py
  design_factory.py
  exporter.py
  builder.py
```

Responsibility split:

- `design_dsl.py`: compatibility facade only
- `errors.py`: `DesignDslError`
- `schema.py`: schema version and allowed-key sets
- `ir.py`: `DesignIR`, `ComponentIR`, `PrimitiveIR`, `PinIR`
- `yaml_io.py`: YAML loader, duplicate-key rejection, include expansion
- `expansion.py`: `_deep_merge`, `$extend`, `$for`
- `expression.py`: interpolation and numeric/unit parsing wrappers
- `primitives.py`: primitive geometry creation and transforms
- `pins.py`: pin parsing and pin-specific transform handling
- `netlist.py`: endpoint normalization and validation
- `derive.py`: derived geometry/netlist metadata
- `design_factory.py`: design class registry and design instantiation
- `exporter.py`: `NativeComponent` and export to Metal
- `builder.py`: `build_ir` and `build_design`

Acceptance:

- Existing public imports keep working:

```python
from qiskit_metal.toolbox_metal.design_dsl import build_ir, build_design
```

- Existing examples continue to work.
- Existing DSL tests pass once environment is correct.
- No schema behavior changes in this milestone.

Risk:

- Moving many private helpers can break imports or circular dependencies.

Mitigation:

- Move dataclasses and constants first.
- Keep function names stable internally where practical.
- Do not add template functionality in this commit.

### Milestone 2: Add Generic Component Template Resolver

Goal: create the layer where qlibrary replacement belongs, without changing exporter.

New modules:

```text
src/qiskit_metal/toolbox_metal/dsl/component_templates.py
src/qiskit_metal/toolbox_metal/dsl/template_registry.py
src/qiskit_metal/toolbox_metal/dsl/template_model.py
```

New template directory:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/
  core/
  qubits/
```

Design syntax:

```yaml
geometry:
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: -1.2mm
        pad_width: 455um
```

Internal behavior:

- Component `class` remains rejected.
- Component `type` is resolved to a YAML template.
- Template defaults merge with instance `options`.
- Result expands into normal `ComponentIR.primitives` and `ComponentIR.pins`.
- Exporter remains primitive-only.

Add to `ComponentIR`:

- `type`
- `options`
- `template`
- `inherited` or minimal provenance

Acceptance:

- A trivial YAML template can produce one rectangle and one pin.
- Instance option override changes the rectangle.
- Unknown option keys are rejected.
- Metadata records resolved component type/options.

Important constraint:

- Do not add any `TransmonPocket` Python generation function. This milestone must be generic.

### Milestone 3: YAML Template Inheritance For QComponent/BaseQubit

Goal: model the option/default chain, not the Python lifecycle.

Add:

```text
dsl_templates/core/qcomponent.yaml
dsl_templates/core/base_qubit.yaml
```

`qcomponent.yaml` should model defaults and metadata:

```yaml
schema: qiskit-metal/component-template/1
id: qcomponent
options:
  pos_x: 0.0um
  pos_y: 0.0um
  orientation: 0.0
  chip: main
  layer: 1
metadata: {}
```

`base_qubit.yaml` should extend `qcomponent`:

```yaml
schema: qiskit-metal/component-template/1
id: base_qubit
extends: qcomponent
options:
  connection_pads: {}
  _default_connection_pads: {}
metadata:
  short_name: Q
merge_rules:
  connection_pads:
    each_entry_extends: _default_connection_pads
    remove_after_resolve:
      - _default_connection_pads
```

Acceptance:

- A component template extending `base_qubit` can define `_default_connection_pads`.
- Instance `connection_pads.readout.loc_W` inherits all missing keys from `_default_connection_pads`.
- Resolved options no longer expose `_default_connection_pads` unless metadata explicitly stores it for debugging.

Risk:

- If this is made too generic too soon, it becomes a template language project.

Mitigation:

- Implement only the map-entry inheritance needed by `BaseQubit`.
- Keep schema strict and small.

### Milestone 4: Static YAML TransmonPocket Pocket

Goal: implement `make_pocket()` in YAML before connection pads.

Add:

```text
dsl_templates/qubits/transmon_pocket.yaml
```

Template should extend `base_qubit` and define defaults:

```yaml
extends: base_qubit
options:
  pad_gap: 30um
  inductor_width: 20um
  pad_width: 455um
  pad_height: 90um
  pocket_width: 650um
  pocket_height: 650um
  _default_connection_pads:
    pad_gap: 15um
    pad_width: 125um
    pad_height: 30um
    pad_cpw_shift: 5um
    pad_cpw_extent: 25um
    cpw_width: cpw_width
    cpw_gap: cpw_gap
    cpw_extend: 100um
    pocket_extent: 5um
    pocket_rise: 65um
    loc_W: +1
    loc_H: +1
```

The YAML recipe should generate:

- `pad_top`
- `pad_bot`
- `rect_pk`
- `rect_jj`

Required generic primitive/expression improvements:

- rectangle with expression-based center:
  - `center: [0, "(pad_height + pad_gap) / 2"]`
- line with expression endpoints:
  - `points: [[0, "-pad_gap / 2"], [0, "pad_gap / 2"]]`
- component transform using `pos_x`, `pos_y`, `orientation`

Acceptance:

- YAML `transmon_pocket` with no connection pads generates the same core qgeometry row names as Python:
  - `pad_top`
  - `pad_bot`
  - `rect_pk`
  - `rect_jj`
- Bounds match Python `TransmonPocket` within tolerance for default options.
- `rect_pk` is subtract.
- `rect_jj` is in the `junction` table and has `width = inductor_width`.

This is the first meaningful `TransmonPocket` replacement slice.

### Milestone 5: Generic Geometry Operation Registry

Goal: support the operations needed by connection pads without hardcoding TransmonPocket.

Python may expose generic operations:

- `rectangle`
- `line_string` / `polyline`
- `buffer`
- `scale`
- `translate`
- `rotate`
- `rotate_position`
- `last_segment`
- `pin_from_normal_segment`

These can wrap existing Metal/draw/shapely helpers:

- `qiskit_metal.draw.rectangle`
- `draw.translate`
- `draw.scale`
- `draw.rotate_position`
- `draw.buffer`
- shapely `LineString`

YAML uses the operations; Python does not know it is building a transmon.

Example style:

```yaml
operations:
  connector_wire_path:
    op: polyline
    points:
      - [0, "${pad.pad_cpw_shift + pad.cpw_width / 2}"]
      - ["${pad.pad_cpw_extent}", "${pad.pad_cpw_shift + pad.cpw_width / 2}"]
      - ["${(options.pocket_width - options.pad_width) / 2 - pad.pocket_extent}", "${pad.pad_cpw_shift + pad.cpw_width / 2 + pad.pocket_rise}"]
      - ["${(options.pocket_width - options.pad_width) / 2 + pad.cpw_extend}", "${pad.pad_cpw_shift + pad.cpw_width / 2 + pad.pocket_rise}"]
```

Acceptance:

- Operations are generic and tested outside `TransmonPocket`.
- Operation registry rejects unknown operations.
- Expressions are evaluated in a constrained context.
- No `make_transmon_pocket` Python function exists.

Risk:

- Expression evaluation can become unsafe or inconsistent.

Mitigation:

- Use a constrained evaluator for arithmetic and units.
- Do not use Python `eval` over raw YAML.
- Keep allowed names and operators explicit.

### Milestone 6: Connection Pad Generator

Goal: implement `make_connection_pads()` and `make_connection_pad(name)` in YAML.

Template needs a generator:

```yaml
generators:
  connection_pads:
    for_each: options.connection_pads
    as: pad
    operations:
      ...
    primitives:
      ...
    pins:
      ...
```

For each pad, generate:

- `{pad.key}_connector_pad`
- `{pad.key}_wire`
- `{pad.key}_wire_sub`
- pin named `{pad.key}`

Required features:

- iteration over map entries
- local variables:
  - `pad.key`
  - `pad.value`
- generated names
- reference operation outputs from primitive specs
- path buffer operation
- pin from final normal segment
- transform sequence:
  1. scale by `loc_W`, `loc_H`
  2. translate by:
     - `loc_W * pad_width / 2`
     - `loc_H * (pad_height + pad_gap / 2 + connection_pad.pad_gap)`
  3. rotate/position by `orientation`, `[pos_x, pos_y]`

Acceptance:

- One `readout` connection pad inherits `_default_connection_pads`.
- Per-pad override changes only that pad.
- Generated qgeometry names match Python naming.
- Generated pin exists and can be connected by netlist.
- Pin width and normal/middle are close to Python output.

### Milestone 7: Parity And Example Replacement

Goal: prove the YAML template replaces the qlibrary authoring path for `TransmonPocket`.

Add example:

```text
examples/dsl/transmon_pocket_2q.metal.yaml
```

Design shape:

```yaml
geometry:
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: -1.2mm
        connection_pads:
          readout:
            loc_W: 1
            loc_H: 1
    Q2:
      type: transmon_pocket
      options:
        pos_x: 1.2mm
        connection_pads:
          readout:
            loc_W: -1
            loc_H: 1
```

Tests:

- Build Python `TransmonPocket` reference design.
- Build YAML `transmon_pocket` design.
- Compare:
  - qgeometry table counts
  - qgeometry row names
  - bounds
  - junction length/width
  - connector wire length
  - subtract flags
  - pin names
  - pin width/gap
  - pin middle/normal/tangent
  - netlist connection works

Acceptance:

- Existing qlibrary classes are not instantiated by DSL.
- YAML design is much shorter than current hand-authored primitive example.
- Parity tests pass within numeric tolerance.

## Specific Corrections To The Original Plan

### Correction 1: Do Not Say "Complete TransmonPocket" In The First Commit

Better wording:

> The first functional target is a YAML-native `TransmonPocket` migration path. The first implementation slice should produce static pocket parity; connection pads and full parity follow in separate commits.

### Correction 2: Do Not Recreate QComponent Runtime In YAML

YAML should not manage:

- design id allocation
- component registration
- overwrite behavior
- qgeometry table usage object state
- `rebuild()`
- renderer default lookup

Those belong in Metal core and `NativeComponent`.

YAML should manage:

- template defaults
- template inheritance
- option validation
- geometry/pin generation recipe
- interface metadata

### Correction 3: "No Python Hardcoding" Needs A Precise Rule

Allowed Python:

- generic template parser
- generic option merge resolver
- generic expression evaluator
- generic geometry operations
- generic pin helper operations
- generic exporter

Disallowed Python:

- `if type == "transmon_pocket": ...`
- Python function that creates `pad_top`, `pad_bot`, `rect_pk`, `rect_jj` specifically for transmons
- Python function that knows `_default_connection_pads` belongs to `TransmonPocket` instead of reading it from YAML
- hidden fallback to instantiate `qlibrary.qubits.TransmonPocket`

### Correction 4: Add A Template Operation Layer Before Connection Pads

Current primitive specs cannot express the full connector algorithm cleanly. The plan needs an explicit operation layer or equivalent helper-expression mechanism before claiming connection pad parity.

### Correction 5: Decide Expression Semantics Early

Current interpolation is text substitution followed by `parse_value`. This is not enough for reusable templates with local variables and formulas.

Need:

- local context
- numeric expression evaluation
- unit parsing
- safe allowed operators
- clear errors for unknown names

Do not use unrestricted Python eval.

## Recommended File Layout

Final target shape:

```text
src/qiskit_metal/toolbox_metal/design_dsl.py
src/qiskit_metal/toolbox_metal/dsl/
  __init__.py
  builder.py
  component_templates.py
  derive.py
  design_factory.py
  errors.py
  expansion.py
  expression.py
  exporter.py
  geometry_ops.py
  ir.py
  netlist.py
  pins.py
  primitives.py
  schema.py
  template_model.py
  template_registry.py
  yaml_io.py
src/qiskit_metal/toolbox_metal/dsl_templates/
  core/
    qcomponent.yaml
    base_qubit.yaml
  qubits/
    transmon_pocket.yaml
examples/dsl/
  transmon_pocket_2q.metal.yaml
tests/
  test_design_dsl.py
  test_design_dsl_templates.py
  test_design_dsl_transmon_pocket.py
```

Keep `design_dsl.py` as:

```python
from qiskit_metal.toolbox_metal.dsl import (
    DesignDslError,
    DesignIR,
    PrimitiveIR,
    PinIR,
    ComponentIR,
    NativeComponent,
    BUILTIN_DESIGNS,
    build_ir,
    export_ir_to_metal,
    build_design,
    register_design,
    clear_user_registry,
)
```

## Tests To Add

### Split Regression

- Existing DSL tests still pass.
- Imports from old `design_dsl.py` still pass.

### Template Resolver

- unknown component `type` rejected
- unknown option key rejected
- template default used
- instance option override wins
- resolved options stored in metadata

### Inheritance

- `transmon_pocket` extends `base_qubit`
- `base_qubit` extends `qcomponent`
- `connection_pads.readout` inherits `_default_connection_pads`
- `_default_connection_pads` does not leak into final runtime options unless kept in debug metadata

### Static Pocket

- default `pad_top`, `pad_bot`, `rect_pk`, `rect_jj`
- rotation and translation match qlibrary
- subtract/helper flags match
- junction width matches `inductor_width`

### Connection Pads

- one pad generated
- multiple pads generated
- per-pad override
- generated geometry names match
- path subtract width is `cpw_width + 2 * cpw_gap`
- pin generated from final path segment
- netlist can connect generated pin

### Parity

- Python qlibrary reference versus YAML template output
- tolerate floating point differences
- compare key semantic geometry, not necessarily full WKT equality at first

## Main Risks

### Risk: Scope Explosion

Full `TransmonPocket` replacement touches parser, template engine, expression engine, geometry operations, pin semantics, examples, and tests.

Mitigation:

- Do not combine with file split.
- Deliver static pocket before connection pads.
- Deliver generic geometry ops before YAML connection pads.

### Risk: Hidden Hardcoding

Pressure to finish quickly may lead to Python logic that is effectively `make_transmon_pocket()`.

Mitigation:

- Require all transmon-specific names and formulas to appear in `transmon_pocket.yaml`.
- Python operation registry must be component-agnostic.
- Add a test that the template can be loaded as data and no qlibrary `TransmonPocket` import occurs.

### Risk: Pin Semantics Mismatch

Current DSL pins are explicit two-point tangent lines. `TransmonPocket.add_pin(..., input_as_norm=True)` uses two path points as a normal direction and computes the tangent pin points.

Mitigation:

- Add a generic pin mode:
  - `mode: tangent_points`
  - `mode: normal_segment`
- Test normal, tangent, middle, width, and gap against qlibrary.

### Risk: Expression Semantics Drift

Metal `parse_value` handles units and some arithmetic, but current DSL interpolation is not enough for nested local formulas.

Mitigation:

- Centralize expression evaluation in `expression.py`.
- Use existing `parse_value` for unit conversion where possible.
- Add tests for formulas used by `TransmonPocket`.

### Risk: Merge Semantics Become Unclear

Template inheritance, design defaults, instance options, and API overrides can conflict.

Mitigation:

- Define precedence:
  1. parent template defaults
  2. child template defaults
  3. design-level defaults by type
  4. instance options
  5. API overrides
- Store resolved options and minimal provenance.
- Reject unknown keys by default.

### Risk: Renderer Compatibility

The current exporter bypasses `QComponent.add_qgeometry` renderer default injection and calls `design.qgeometry.add_qgeometry` directly. Existing tests intentionally assert renderer defaults are not injected.

Mitigation:

- Keep current behavior for v3 templates.
- Later add explicit renderer metadata support if needed.
- Do not mix renderer behavior into the TransmonPocket migration.

## Final Feasibility Decision

The plan is feasible after these adjustments:

1. Treat file splitting as a separate behavior-preserving milestone.
2. Keep `QComponent` and Metal core.
3. Represent `QComponent/BaseQubit/TransmonPocket` in YAML as defaults, metadata, merge rules, and geometry recipes, not as runtime lifecycle.
4. Add a generic template resolver before attempting `TransmonPocket`.
5. Add generic geometry/pin operations before connection pad parity.
6. Make `TransmonPocket` parity the first migration milestone, not the first code commit.

The most important change is to replace:

> "第一步完整替代 TransmonPocket"

with:

> "第一阶段以完整替代 TransmonPocket 为目标，分多步交付；第一步先拆文件，第一功能步先做 YAML template resolver 和 static pocket parity."

This keeps the original direction intact while making the implementation reviewable and testable.
