# DSL v3 YAML TransmonPocket Final Implementation Plan

Date: 2026-05-11

Target worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Target module:

`src/qiskit_metal/toolbox_metal/design_dsl.py`

Final goal:

Build a YAML-native replacement path for qlibrary template authoring, with the first complete target being `TransmonPocket`. The implementation must cover the effective behavior chain:

`TransmonPocket -> BaseQubit -> QComponent`

The component recipe must live in YAML templates. Python may provide generic DSL infrastructure and generic geometry/pin helper operations, but Python must not hardcode `TransmonPocket` behavior.

## Confirmed Direction

This plan is the implementation plan. It is not an evaluation.

The implementation will:

- Split the oversized `design_dsl.py` into a maintainable `dsl/` package.
- Keep `design_dsl.py` as a backward-compatible public facade.
- Keep `QDesign`, `QComponent`, `NativeComponent`, qgeometry tables, pins, and net_info.
- Stop using qlibrary component classes such as `TransmonPocket` as the DSL build target.
- Implement reusable YAML component templates.
- Implement `qcomponent.yaml`, `base_qubit.yaml`, and `transmon_pocket.yaml`.
- Make `TransmonPocket` the only qlibrary-template replacement target in the first phase.
- Preserve current primitive-only v3 behavior while adding the template layer above it.

The implementation will not:

- Delete `src/qiskit_metal/qlibrary`.
- Instantiate `qiskit_metal.qlibrary.qubits.TransmonPocket` from DSL.
- Add `if type == "transmon_pocket"` construction logic in Python.
- Encode `pad_top`, `pad_bot`, `rect_pk`, `rect_jj`, or connection-pad formulas in Python.
- Attempt to migrate unrelated qlibrary components in the first phase.

## Definition Of Done

The phase is complete when a YAML design can instantiate two transmon pockets like this:

```yaml
schema: qiskit-metal/design-dsl/3

vars:
  qx: 1.2mm
  cpw_width: 12um
  cpw_gap: 7um

hamiltonian:
  subsystems:
    Q1: {model: transmon}
    Q2: {model: transmon}

circuit:
  Q1: {type: transmon}
  Q2: {type: transmon}

netlist:
  connections:
    - {from: Q1.readout, to: Q2.readout}

geometry:
  design:
    class: DesignPlanar
    chip: {size: 6mm x 6mm}
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: "-${vars.qx}"
        connection_pads:
          readout:
            loc_W: 1
            loc_H: 1
            cpw_width: "${vars.cpw_width}"
            cpw_gap: "${vars.cpw_gap}"
    Q2:
      type: transmon_pocket
      options:
        pos_x: "${vars.qx}"
        connection_pads:
          readout:
            loc_W: -1
            loc_H: 1
            cpw_width: "${vars.cpw_width}"
            cpw_gap: "${vars.cpw_gap}"
```

and the resulting Metal design contains:

- `NativeComponent` instances named `Q1` and `Q2`
- qgeometry rows equivalent to Python `TransmonPocket` for:
  - `pad_top`
  - `pad_bot`
  - `rect_pk`
  - `rect_jj`
  - `readout_connector_pad`
  - `readout_wire`
  - `readout_wire_sub`
- generated pins named `readout`
- working netlist connection through `design.connect_pins`
- resolved component type/options in `design.metadata["dsl_chain"]`
- no qlibrary `TransmonPocket` instantiation

## Architecture After Implementation

### Public Compatibility Layer

Keep:

```text
src/qiskit_metal/toolbox_metal/design_dsl.py
```

This file becomes a facade only. It re-exports the public API:

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

No feature logic stays in this file.

### New DSL Package

Create:

```text
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
```

Responsibilities:

- `errors.py`: `DesignDslError`
- `schema.py`: schema version and allowed key sets
- `ir.py`: `DesignIR`, `ComponentIR`, `PrimitiveIR`, `PinIR`
- `yaml_io.py`: YAML loading, duplicate-key rejection, `$include`
- `expansion.py`: `$extend`, `$for`, generic merge utilities
- `expression.py`: interpolation and safe numeric/unit expression evaluation
- `geometry_ops.py`: generic geometry operation registry
- `primitives.py`: primitive parsing and transform application
- `pins.py`: pin parsing and pin helper modes
- `netlist.py`: endpoint normalization and validation
- `derive.py`: derived geometry/netlist metadata
- `design_factory.py`: design class registry and design instantiation
- `exporter.py`: `NativeComponent` and Metal export
- `template_model.py`: template dataclasses/normalized model
- `template_registry.py`: built-in and file template resolution
- `component_templates.py`: component `type + options` expansion
- `builder.py`: `build_ir`, `build_design`

### YAML Template Location

Create:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/
  core/
    qcomponent.yaml
    base_qubit.yaml
  qubits/
    transmon_pocket.yaml
```

The built-in registry maps:

```text
qcomponent      -> core/qcomponent.yaml
base_qubit      -> core/base_qubit.yaml
transmon_pocket -> qubits/transmon_pocket.yaml
```

## Data Flow

The final data flow is:

```text
YAML design
  -> load/include
  -> root validation
  -> vars/circuit/hamiltonian/netlist interpolation
  -> component type resolution
  -> YAML template inheritance
  -> option default resolution
  -> BaseQubit-style connection_pads expansion
  -> YAML operation/generator expansion
  -> ComponentIR/PrimitiveIR/PinIR
  -> derived metadata
  -> NativeComponent export
  -> qgeometry/pins/net_info
  -> design.metadata["dsl_chain"]
```

The exporter remains primitive-only. Templates expand before export.

## Commit Plan

### Commit 1: Split `design_dsl.py` Without Behavior Change

Purpose:

Make room for template work by separating the current 1161-line module into focused modules.

Changes:

- Add `src/qiskit_metal/toolbox_metal/dsl/`.
- Move existing classes/functions into modules listed above.
- Keep public names exported through `dsl/__init__.py`.
- Replace `design_dsl.py` with the compatibility facade.
- Do not add component-template features in this commit.
- Do not change existing DSL behavior.

Acceptance:

- Existing examples still build.
- Existing `tests/test_design_dsl.py` still passes in the correct environment.
- Existing imports from `qiskit_metal.toolbox_metal.design_dsl` still work.
- `design_dsl.py` is reduced to facade size.

### Commit 2: Add Component Template Model And Registry

Purpose:

Introduce YAML component templates as data, without yet implementing full TransmonPocket.

Changes:

- Add `template_model.py`.
- Add `template_registry.py`.
- Add `component_templates.py`.
- Add built-in template lookup.
- Add component keys:
  - `type`
  - `options`
- Continue rejecting component `class`.
- Add `ComponentIR` fields:
  - `type`
  - `options`
  - `template`
  - `inherited`

Template schema minimum:

```yaml
schema: qiskit-metal/component-template/1
id: example_template
extends: null
options: {}
metadata: {}
geometry:
  primitives: {}
  pins: {}
```

Acceptance:

- A trivial template can produce one rectangle and one pin.
- Instance `options` override template defaults.
- Unknown template type is rejected.
- Unknown option key is rejected.
- Resolved type/options appear in metadata.
- No qlibrary component is imported or instantiated.

### Commit 3: Add Safe Expression And Local Context

Purpose:

Support reusable templates without hard-coded `${circuit.Q1...}` paths.

Changes:

- Centralize expression handling in `expression.py`.
- Add local context roots:
  - `vars`
  - `circuit`
  - `hamiltonian`
  - `netlist`
  - `component`
  - `options`
  - generator locals such as `pad`
- Support numeric/unit arithmetic needed by TransmonPocket formulas.
- Keep expression evaluation constrained.

Allowed:

- arithmetic operators: `+`, `-`, `*`, `/`, unary `+`, unary `-`
- parentheses
- numeric values with Metal units
- resolved context names

Forbidden:

- Python attribute execution
- function calls except whitelisted DSL helpers
- imports
- arbitrary `eval`

Acceptance:

- Expressions like `"${(options.pad_height + options.pad_gap) / 2}"` resolve to a numeric value with units.
- Existing simple `${vars.x}` interpolation continues to work.
- Unknown names fail with clear `DesignDslError`.
- Expressions work consistently in primitive center, size, points, width, gap, and transforms.

### Commit 4: Add Generic Geometry Operation Registry

Purpose:

Expose reusable geometry operations to YAML templates without hardcoding TransmonPocket.

Changes:

- Add `geometry_ops.py`.
- Register generic operations:
  - `rectangle`
  - `polyline`
  - `line`
  - `polygon`
  - `buffer`
  - `scale`
  - `translate`
  - `rotate`
  - `rotate_position`
  - `last_segment`
- Wrap existing Metal/shapely helpers where appropriate:
  - `qiskit_metal.draw.rectangle`
  - `qiskit_metal.draw.translate`
  - `qiskit_metal.draw.scale`
  - `qiskit_metal.draw.rotate_position`
  - `qiskit_metal.draw.buffer`
  - shapely `LineString`

YAML operation shape:

```yaml
operations:
  my_rect:
    op: rectangle
    width: "${options.pad_width}"
    height: "${options.pad_height}"
    xoff: 0
    yoff: "${(options.pad_height + options.pad_gap) / 2}"
```

Acceptance:

- Operation outputs can be referenced by generated primitives.
- Unknown operations are rejected.
- Operation names are local to a component/template expansion.
- No operation is TransmonPocket-specific.

### Commit 5: Add Pin Modes Needed For TransmonPocket

Purpose:

Support both current explicit pin points and qlibrary `input_as_norm=True` semantics.

Changes:

- Move pin logic into `pins.py`.
- Keep existing pin syntax:

```yaml
points: [[x1, y1], [x2, y2]]
mode: tangent_points
```

- Add normal-segment pin mode:

```yaml
mode: normal_segment
from_operation: readout_wire
segment: last
width: "${pad.value.cpw_width}"
gap: "${pad.value.cpw_gap}"
```

Behavior:

- `tangent_points` matches current DSL behavior.
- `normal_segment` reproduces `QComponent.add_pin(..., input_as_norm=True)`:
  - use last two path points as normal direction
  - middle is the final path point
  - tangent points are computed from width
  - normal/tangent/middle are stored consistently by `component.add_pin`

Acceptance:

- Existing pin tests still pass.
- New tests compare `normal_segment` pin against `add_pin(input_as_norm=True)` behavior.
- Generated TransmonPocket connection pad pin can be connected by netlist.

### Commit 6: Add YAML `qcomponent.yaml`

Purpose:

Represent the default option layer of `QComponent` in YAML.

File:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/core/qcomponent.yaml
```

Content:

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
geometry:
  transform:
    translate: ["${options.pos_x}", "${options.pos_y}"]
    rotate: "${options.orientation}"
```

Acceptance:

- A test template extending `qcomponent` inherits these options.
- Instance `options.pos_x` and `options.orientation` affect generated geometry.
- Runtime component lifecycle still comes from `NativeComponent/QComponent`, not YAML.

### Commit 7: Add YAML `base_qubit.yaml`

Purpose:

Represent the `BaseQubit` option layer and connection-pad inheritance.

File:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/core/base_qubit.yaml
```

Content:

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
    remove_from_resolved_options:
      - _default_connection_pads
```

Acceptance:

- A child template can define `_default_connection_pads`.
- Instance `connection_pads.readout` inherits missing fields from `_default_connection_pads`.
- Unknown connection pad option keys are rejected after defaults are known.
- Resolved metadata records the inherited connection pad values.

### Commit 8: Add Static YAML `transmon_pocket.yaml`

Purpose:

Implement `TransmonPocket.make_pocket()` in YAML.

File:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml
```

Template defaults:

```yaml
schema: qiskit-metal/component-template/1
id: transmon_pocket
extends: base_qubit
metadata:
  short_name: Pocket
  qgeometry_tables: [poly, path, junction]
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

Static pocket operations/primitives:

- `pad_top`
- `pad_bot`
- `rect_pk`
- `rect_jj`

Required generated primitive semantics:

- `pad_top`, `pad_bot` are `poly`
- `rect_pk` is `poly`, `subtract: true`
- `rect_jj` is `junction`, `width: ${options.inductor_width}`
- all use `options.chip` and `options.layer`
- all are transformed by inherited `pos_x`, `pos_y`, `orientation`

Acceptance:

- YAML `transmon_pocket` with no connection pads generates the same core rows as Python `TransmonPocket`.
- Bounds match the qlibrary reference within tolerance.
- Junction length is `pad_gap`.
- Junction width is `inductor_width`.
- No Python `TransmonPocket` class is instantiated.

### Commit 9: Add YAML Generator Support For `connection_pads`

Purpose:

Implement `TransmonPocket.make_connection_pads()` in YAML.

Template generator shape:

```yaml
generators:
  connection_pads:
    for_each: options.connection_pads
    as: pad
    operations:
      connector_pad:
        op: rectangle
        width: "${pad.value.pad_width}"
        height: "${pad.value.pad_height}"
        xoff: "-${pad.value.pad_width} / 2"
        yoff: "${pad.value.pad_height} / 2"
      connector_wire_path:
        op: polyline
        points:
          - [0, "${pad.value.pad_cpw_shift + pad.value.cpw_width / 2}"]
          - ["${pad.value.pad_cpw_extent}", "${pad.value.pad_cpw_shift + pad.value.cpw_width / 2}"]
          - ["${(options.pocket_width - options.pad_width) / 2 - pad.value.pocket_extent}", "${pad.value.pad_cpw_shift + pad.value.cpw_width / 2 + pad.value.pocket_rise}"]
          - ["${(options.pocket_width - options.pad_width) / 2 + pad.value.cpw_extend}", "${pad.value.pad_cpw_shift + pad.value.cpw_width / 2 + pad.value.pocket_rise}"]
      connector_wire_sub:
        op: buffer
        source: connector_wire_path
        distance: "${pad.value.cpw_width / 2 + pad.value.cpw_gap}"
      placed:
        op: transform_group
        sources: [connector_pad, connector_wire_path, connector_wire_sub]
        steps:
          - op: scale
            xfact: "${pad.value.loc_W}"
            yfact: "${pad.value.loc_H}"
            origin: [0, 0]
          - op: translate
            xoff: "${pad.value.loc_W * options.pad_width / 2}"
            yoff: "${pad.value.loc_H * (options.pad_height + options.pad_gap / 2 + pad.value.pad_gap)}"
          - op: rotate_position
            angle: "${options.orientation}"
            pos: ["${options.pos_x}", "${options.pos_y}"]
    primitives:
      "${pad.key}_connector_pad":
        type: poly.from_operation
        operation: placed.connector_pad
        chip: "${options.chip}"
        layer: "${options.layer}"
      "${pad.key}_wire":
        type: path.from_operation
        operation: placed.connector_wire_path
        width: "${pad.value.cpw_width}"
        chip: "${options.chip}"
        layer: "${options.layer}"
      "${pad.key}_wire_sub":
        type: path.from_operation
        operation: placed.connector_wire_path
        width: "${pad.value.cpw_width + 2 * pad.value.cpw_gap}"
        subtract: true
        chip: "${options.chip}"
        layer: "${options.layer}"
    pins:
      "${pad.key}":
        mode: normal_segment
        from_operation: placed.connector_wire_path
        segment: last
        width: "${pad.value.cpw_width}"
        gap: "${pad.value.cpw_gap}"
        chip: "${options.chip}"
```

Implementation notes:

- Exact YAML field names can be adjusted during implementation, but the recipe must stay in YAML.
- Python provides `transform_group` generically, not for transmons only.
- `path.from_operation` uses operation geometry instead of point lists.

Acceptance:

- `connection_pads.readout` generates:
  - `readout_connector_pad`
  - `readout_wire`
  - `readout_wire_sub`
  - pin `readout`
- Per-pad overrides work.
- Multiple pads work.
- Missing pad fields inherit `_default_connection_pads`.
- Generated pin matches qlibrary `input_as_norm=True` semantics within tolerance.

### Commit 10: Add TransmonPocket Example And Replace Primitive Demo Usage

Purpose:

Show the intended authoring style.

Add:

```text
examples/dsl/transmon_pocket_2q.metal.yaml
examples/dsl/run_transmon_pocket_demo.py
```

Update:

```text
examples/dsl/README.md
```

README must say:

- primitive-only components are still supported
- qlibrary `class` components remain rejected
- `type: transmon_pocket` is the YAML-native replacement path
- the template expands to primitives/pins before export

Acceptance:

- Demo builds a two-transmon design.
- Demo prints qgeometry row counts, pins, net_info, and metadata template info.
- Existing examples remain valid.

### Commit 11: Add Parity Test Suite

Purpose:

Confirm YAML `transmon_pocket` replaces the qlibrary authoring path.

Add:

```text
tests/test_design_dsl_templates.py
tests/test_design_dsl_transmon_pocket.py
```

Test groups:

1. Template resolver:
   - unknown type rejected
   - unknown option rejected
   - defaults applied
   - instance overrides applied
   - metadata records resolved options

2. QComponent/BaseQubit templates:
   - `base_qubit` inherits `qcomponent`
   - `connection_pads` inherit `_default_connection_pads`
   - `_default_connection_pads` removed from runtime resolved options

3. Static TransmonPocket:
   - `pad_top`
   - `pad_bot`
   - `rect_pk`
   - `rect_jj`
   - subtract flags
   - junction width
   - bounds against qlibrary reference

4. Connection pads:
   - generated connector primitives
   - generated pin
   - pin middle/normal/tangent
   - netlist connection

5. No qlibrary construction:
   - monkeypatch qlibrary `TransmonPocket.__init__` to fail
   - build DSL `type: transmon_pocket`
   - assert build still succeeds

Acceptance:

- All current DSL tests pass.
- New template tests pass.
- New TransmonPocket parity tests pass within tolerance.

## Implementation Rules

### Rule 1: YAML Owns Component-Specific Logic

All transmon-specific names and formulas live in:

```text
src/qiskit_metal/toolbox_metal/dsl_templates/qubits/transmon_pocket.yaml
```

Examples:

- `pad_top`
- `pad_bot`
- `rect_pk`
- `rect_jj`
- `readout_connector_pad`
- `readout_wire`
- `readout_wire_sub`
- default option values
- connection pad formulas

### Rule 2: Python Owns Generic Infrastructure

Python may implement:

- YAML loading
- template registry
- template inheritance
- option merge
- expression evaluation
- generic geometry operations
- generic pin modes
- primitive IR
- exporter

Python may not implement:

- transmon-specific geometry formulas
- transmon-specific option defaults
- qlibrary class fallback
- component-specific branches by template id

### Rule 3: Keep The Exporter Primitive-Only

Templates must lower to:

- `ComponentIR`
- `PrimitiveIR`
- `PinIR`

Then existing export writes:

- qgeometry rows
- pins
- net_info
- metadata

### Rule 4: Preserve Strict Validation

Continue rejecting:

- duplicate YAML keys
- unknown root keys
- unknown geometry keys
- unknown component keys
- unknown primitive keys
- unknown pin keys
- qlibrary `class` entries
- invalid netlist endpoints
- unknown chips

Extend strict validation to templates:

- unknown template type
- unknown option key
- unknown operation
- unknown operation reference
- unknown generator variable
- invalid expression

### Rule 5: Preserve Backward Compatibility

Existing primitive-only DSL files must continue to work.

Existing imports from `design_dsl.py` must continue to work.

Existing examples remain valid, even if the new TransmonPocket example becomes the recommended path.

## Resolved Open Design Choices

### Keep QComponent

Decision:

Keep `QComponent` through `NativeComponent`.

Reason:

The goal is to replace qlibrary component templates as DSL authoring/build targets, not to replace Metal's design container, qgeometry tables, pin model, and renderer integration.

### Template Type Syntax

Decision:

Use:

```yaml
type: transmon_pocket
options: {}
```

Do not use:

```yaml
class: TransmonPocket
```

### Template Defaults

Decision:

Template defaults are YAML data under `options`.

Merge order:

1. parent template options
2. child template options
3. design-level defaults by type, if added later
4. instance `options`
5. API `overrides`

### Connection Pad Defaults

Decision:

Implement a generic map-entry inheritance rule:

```yaml
merge_rules:
  connection_pads:
    each_entry_extends: _default_connection_pads
```

This reproduces the important behavior of `BaseQubit._set_options_connection_pads()`.

### Pin Semantics

Decision:

Support both:

- tangent-point pins
- normal-segment pins

This is necessary because existing DSL pins are tangent-point pins, while `TransmonPocket` uses `add_pin(..., input_as_norm=True)`.

### Renderer Defaults

Decision:

Do not add renderer-default injection in this phase.

Reason:

Current v3 tests intentionally verify that exporter does not inject renderer qgeometry defaults. TransmonPocket migration should not change renderer behavior.

## Worktree Safety

Before each implementation commit:

- run `git status --short`
- inspect any modified files before editing
- preserve unrelated user/agent changes
- do not revert user work

Known current state at plan time:

- `src/qiskit_metal/toolbox_metal/design_dsl.py` has uncommitted comment changes from another context.
- `.codex/` contains planning/evaluation documents.
- Do not overwrite unrelated changes.

## Final Execution Order

Use this exact order:

1. Establish repeatable test command/environment.
2. Split `design_dsl.py` with no behavior change.
3. Add generic template model and registry.
4. Add safe expression/local context.
5. Add generic geometry operation registry.
6. Add pin modes, including `normal_segment`.
7. Add `qcomponent.yaml`.
8. Add `base_qubit.yaml`.
9. Add static `transmon_pocket.yaml` pocket geometry.
10. Add `connection_pads` generator.
11. Add two-transmon YAML example.
12. Add parity and no-qlibrary-construction tests.
13. Update README with the new authoring path.

This order keeps the implementation reviewable while still making `TransmonPocket` the first and only qlibrary-template replacement target in the phase.

## Final Success Statement

After this plan is implemented, DSL v3 will support two authoring levels:

1. primitive-native components, as it does now
2. YAML-native component templates, starting with `transmon_pocket`

The `transmon_pocket` template will reproduce the practical `TransmonPocket -> BaseQubit -> QComponent` behavior chain through YAML defaults, YAML merge rules, YAML geometry recipes, and generic Python DSL infrastructure.

That is the correct first complete step toward removing qlibrary Python components from the DSL construction path.
