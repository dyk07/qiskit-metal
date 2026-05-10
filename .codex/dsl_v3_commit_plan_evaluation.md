# DSL v3 Commit and Plan Evaluation

Date: 2026-05-11

Evaluator role: independent design review agent.

Target worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Scope checked lightly:

- Recent commits:
  - `1d0399e9 dsl v3-0`
  - `99772d82 fixing dsl v3-0`
- `src/qiskit_metal/toolbox_metal/design_dsl.py`
- `examples/dsl/README.md`
- `examples/dsl/chain_2q_native.metal.yaml`
- `examples/dsl/native_2q_minimal.metal.yaml`
- `examples/dsl/run_chain_demo.py`
- `tests/test_design_dsl.py`
- Prior plan/evaluation: `.codex/dsl_v3_template_evaluation.md`
- Minimal reference check against `qlibrary/qubits/transmon_pocket.py` and `qlibrary/core/qubit.py`

No core code was modified for this evaluation. This document is the only file created.

## Executive Judgment

The last two commits are a real and useful step toward a Hamiltonian-Circuit-Netlist-Geometry chain, but they are not yet the full chain promised by the original requirement. They establish a primitive-native vertical slice: YAML can carry Hamiltonian and circuit sections, interpolate some circuit data into geometry, build primitive/pin IR, export directly to Metal qgeometry/pins/net_info, and store derived geometry/netlist metadata. That is meaningful progress.

However, the current v3 implementation is still primitive-first authoring. It does not yet provide YAML-native component templates with option schemas, local option scope, qlibrary-like default inheritance, generated connection pads, or semantic propagation from geometry back into circuit/Hamiltonian models. It removes `TransmonPocket` from the examples as an instantiated build target, but it does not replace the capability of `TransmonPocket`.

My recommended interpretation of "remove Qiskit library like TransmonPocket" is:

> Stop using `src/qiskit_metal/qlibrary` Python component classes as the DSL authoring and build target. Do not immediately delete Metal core, `QDesign`, `QComponent`, qgeometry, pin, or renderer infrastructure. Do not delete the existing qlibrary during migration.

The next implementation should be a narrow component-template resolver that expands `type + options` YAML templates into the current primitive/pin IR. Do not jump straight to a large expression language, full package manager, or wholesale qlibrary removal.

## 1. Did The Two Commits Advance The Original Requirement?

Original requirement:

> Start to extend the file format to Hamiltonian-Circuit-Netlist-Geometry full chain, and the information of circuit can be passed up and down. (Next: remove Qiskit library like TransmonPocket) to do: to remove Qiskit library like TransmonPocket

### Commit `1d0399e9 dsl v3-0`

This commit created the first native v3 DSL vertical slice:

- New `design_dsl.py`.
- New YAML examples.
- New README.
- New tests.
- Introduced root sections for `hamiltonian`, `circuit`, `netlist`, and `geometry`.
- Introduced `DesignIR`, `ComponentIR`, `PrimitiveIR`, and `PinIR`.
- Introduced `NativeComponent`, a lightweight `QComponent` subclass used only as an owner for native DSL geometry.
- Export path writes directly to:
  - `design.qgeometry`
  - component pins
  - `design.net_info` through `design.connect_pins`
  - `design.metadata["dsl_chain"]`
- Examples no longer instantiate `TransmonPocket`, `RouteMeander`, etc.

Assessment: this is a genuine initial full-chain skeleton. It proves that a YAML file can describe the chain and produce a Metal design without naming qlibrary components.

Limit: the "full chain" is mostly structural. Hamiltonian and circuit are preserved and interpolated; they are not yet validated or semantically bound to geometry/netlist.

### Commit `99772d82 fixing dsl v3-0`

This commit mainly hardens the first version:

- Adds schema-level allowed-key sets for root, geometry, design, component, primitive, pin, netlist, and chip sections.
- Rejects duplicate YAML keys.
- Rejects typo keys such as `netlsit`, `clas`, `widht`, `gpa`, `szie`.
- Validates `$include` cycles.
- Validates `$extend` values.
- Validates transforms more strictly.
- Validates netlist endpoint reuse and self-connections.
- Validates primitive/pin chip names during export.
- Defaults omitted pin gap to `width * 0.6`.
- Fixes `DesignMultiPlanar` short-name resolution to `MultiPlanar`.
- Adds many tests around malformed YAML and edge cases.

Assessment: this commit increases reliability and makes the file format less ambiguous. It does not significantly deepen Hamiltonian/Circuit semantics, but it makes the primitive-native path safer.

### Net Assessment

Real progress:

- The code now has a Hamiltonian-Circuit-Netlist-Geometry document shape.
- Circuit data can flow downward into geometry through interpolation, for example `${circuit.Q1.pad_width}`.
- Hamiltonian can reference circuit data, for example `${circuit.Q1.C}` in the example.
- Netlist connects explicit pins and exports to Metal net info.
- Geometry-derived data flows upward into `ir.derived` and `design.metadata["dsl_chain"]["derived"]`.
- Export avoids instantiating qlibrary classes such as `TransmonPocket`.

Not yet achieved:

- No semantic circuit schema.
- No Hamiltonian schema or model binding.
- No relation that says a junction primitive corresponds to a Hamiltonian Josephson energy symbol.
- No circuit parameter extraction from geometry beyond generic bounds/lengths/pin middles.
- No propagation policy for resolving conflicts between top-level circuit values, component options, geometry-derived values, and Hamiltonian defaults.
- No template-generated circuit/Hamiltonian defaults.
- No ports, roles, capacitance/coupling hints, or netlist metadata.
- No replacement for qlibrary component default behavior.

Verdict:

The commits deliver a credible v3 prototype and a strong parser/export baseline. They do not yet deliver a true "full chain" in the scientific or architectural sense.

## 2. Correct Interpretation Of "Remove Qiskit Library Like TransmonPocket"

There are three possible interpretations:

1. Remove `qlibrary` Python components as DSL authoring/build targets.
2. Remove all Metal core dependencies, including `QDesign`, `QComponent`, qgeometry, pins, net_info, renderers, and parsing utilities.
3. Delete `src/qiskit_metal/qlibrary` from the project.

Only interpretation 1 is the right near-term target.

The current v3 code still reasonably depends on Metal core:

- `QDesign` classes are still needed as the design container.
- `QComponent` is still used by `NativeComponent` to own geometry and pins.
- `design.qgeometry.add_qgeometry` remains the correct bridge into existing renderers.
- `design.connect_pins` and `design.net_info` remain useful.
- `parse_value` remains useful for Metal unit parsing.

Those are not the same as depending on `TransmonPocket` as a construction primitive. The requirement says "like TransmonPocket", which points to qlibrary component templates, not the entire Metal data model.

Deleting `qlibrary` now would be counterproductive:

- Existing users and tests likely depend on it.
- It provides reference behavior for migration.
- It is the best source of parity tests while YAML-native templates mature.
- Many components contain nontrivial geometry algorithms that need staged replacement.

Recommended wording for the project goal:

> The v3 DSL should stop naming or instantiating qlibrary components. Reusable component behavior such as `TransmonPocket` should be represented by YAML-native templates that expand into primitive/pin IR, while the exporter continues to target the existing Metal design/qgeometry/netlist infrastructure.

## 3. Distance From Current Primitive-Only v3 To YAML Templates Replacing qlibrary

Current v3 can be summarized as:

`YAML sections -> interpolation -> primitive/pin IR -> NativeComponent/qgeometry/pins/net_info -> metadata`

That is useful, but it is still far from:

`YAML component type -> option defaults/inheritance -> generated primitives/pins/ports -> circuit/Hamiltonian contributions -> exported qgeometry/netlist -> derived feedback`

The largest gaps are below.

### Component Type Identity

Current examples use `$extend: transmon_pad_pair`, but this is only a structural YAML merge. There is no first-class component type such as:

```yaml
Q1:
  type: transmon_pocket
  options:
    pad_width: 455um
```

Without type identity, there is no stable place for:

- option schema
- default values
- documentation
- versioning
- interface declarations
- generated pin contracts
- circuit/Hamiltonian defaults
- migration parity tests

### Local Option Scope

Current templates hard-code global paths such as `${circuit.Q1.pad_width}`. The example shows the problem directly: `Q2` repeats the whole primitive list because the template is not truly local.

A reusable component template needs local scope:

- `${component.name}`
- `${options.pad_width}`
- `${options.connection_pads.readout.loc_W}`
- `${vars.*}`
- optional read access to `${circuit.*}` and `${hamiltonian.*}`

The template should not need to know it is expanding as `Q1` or `Q2`.

### qlibrary-Style Default Inheritance

`TransmonPocket` relies on layered defaults:

- `QComponent.default_options`
- `BaseQubit.default_options`
- `TransmonPocket.default_options`
- `_default_connection_pads`
- instance `options`
- `options_connection_pads`

`BaseQubit._set_options_connection_pads()` deep-copies `_default_connection_pads` for each named connection pad and merges per-pad overrides. Current v3 does not have an equivalent map-level default inheritance mechanism.

This is the core missing feature for replacing `TransmonPocket` authoring ergonomics.

### Primitive Generation

Current primitive support is intentionally small:

- `poly.rectangle`
- `poly.polygon`
- `path.line`
- `path.polyline`
- `junction.line`

`TransmonPocket` needs more than static primitive lists:

- top/bottom pad placement derived from pad dimensions and gap
- pocket subtract geometry
- junction line width and endpoints
- orientation and position transforms
- connection pads generated from a map
- connector wire path
- subtract path around connector wire
- pin creation from the final connector segment

Some of this can be done with current primitives if repeated manually. It is not yet reusable or template-generated.

### Bidirectional Chain Semantics

Downward flow currently exists in a simple form:

`vars -> circuit -> hamiltonian/netlist/geometry interpolation`

Upward flow is currently generic derived metadata:

`geometry/pins/netlist -> ir.derived -> design.metadata`

That upward flow does not yet update or enrich `circuit` or `hamiltonian` with model-aware data. For example, there is no rule that says:

- `Q1.jj` is the junction primitive for Hamiltonian subsystem `Q1`.
- a geometry length contributes to a circuit inductance/capacitance estimate.
- a pin with role `readout` creates a circuit coupling node.
- a netlist edge with role `coupler` maps to Hamiltonian coupling metadata.

### Estimated Distance

For a minimal `TransmonPocket`-like YAML template:

- Needs component `type + options`: small to medium.
- Needs option defaults and unknown-key validation: medium.
- Needs local expression context: medium.
- Needs arithmetic with units formalized: medium.
- Needs connection pad map generator: medium to high.
- Needs helper functions for pin generation from geometry/anchors: medium to high.
- Needs circuit/Hamiltonian contributions: medium, if kept metadata-only at first.
- Needs qlibrary parity: high, because qlibrary behavior includes many geometry details and renderer expectations.

Bottom line: primitive-only v3 is a solid lower layer. It is not close enough to claim qlibrary template replacement yet.

## 4. Evaluation Of The Prior YAML-Native Template Plan

I read `.codex/dsl_v3_template_evaluation.md`. My independent view is that its direction is mostly correct:

- Keep the exporter primitive-only.
- Add component template loading above the current IR.
- Use `type + options` instead of qlibrary `class`.
- Use local `options` scope.
- Add option schema/defaults.
- Represent connection pads as maps.
- Expand YAML templates into existing `ComponentIR`, `PrimitiveIR`, and `PinIR`.
- Preserve existing strict validation.
- Migrate qlibrary gradually.

Where the plan is especially right:

- It correctly avoids reintroducing qlibrary classes as hidden construction targets.
- It correctly identifies list replacement as a blocker.
- It correctly identifies hard-coded `${circuit.Q1...}` paths as non-reusable.
- It correctly treats `TransmonPocket` replacement as a template/default/generator problem, not just a primitive syntax problem.
- It correctly says the current v3 should not be marketed as replacing `TransmonPocket`.

Where the plan risks over-design:

- A full external template package/discovery/versioning system may be too much for the next slice. Start with one explicit local import path or one built-in template registry entry.
- A broad expression language should not be introduced all at once. Start with constrained numeric expressions already needed by current YAML strings and reject unsafe/general Python evaluation.
- Provenance for every inherited key is valuable, but a complete provenance tree can wait. For the first slice, store resolved defaults and mark only top-level source categories: template default, design default, instance override, API override.
- Netlist role metadata and circuit/Hamiltonian publish hooks should be staged after the component template resolver is stable. Adding them too early will churn schemas.
- Patch operations like `$delete`, `$append`, `$replace`, `$merge_by` are powerful but can wait if primitives, pins, and connection pads are represented as maps before lowering to lists.

Where the plan may be insufficient:

- It needs an explicit conflict-resolution model for circuit values versus component options. For example, if `circuit.Q1.pad_width` and `geometry.components.Q1.options.pad_width` disagree, the resolver must either define precedence or reject the conflict.
- It needs a clear split between raw source metadata and resolved metadata. Current `to_metadata()` stores resolved chain data, but future debugging will need both.
- It needs a formal policy for generated names. qlibrary parity depends on stable qgeometry row names and pin names.
- It needs renderer compatibility tests, not just IR tests, once more primitive/table options are added.
- It needs a planned migration path for `input_as_norm=True` pin semantics used by qlibrary components. Current v3 pins are explicit endpoints with a width check; qlibrary often derives pin normal/direction from path geometry.
- It needs to decide how `NativeComponent.component_metadata` will advertise future qgeometry table usage beyond the current `poly`, `path`, and `junction`.

## 5. Recommended Implementation Strategy

### Short Term

Keep the current primitive exporter and harden the layer immediately above it.

Recommended short-term changes:

- Add first-class component template syntax:

```yaml
geometry:
  templates:
    transmon_pocket:
      schema: qiskit-metal/component-template/1
      options: {...}
      primitives: {...}
      pins: {...}
  components:
    Q1:
      type: transmon_pocket
      options: {...}
```

- Allow `type` and `options` on components, but keep `class` rejected.
- Expand component templates into the existing `ComponentIR` without changing `export_ir_to_metal`.
- Add local context:
  - `component.name`
  - `options`
  - `vars`
  - `circuit`
  - `hamiltonian`
  - `netlist`
- Add option defaults and unknown option-key rejection.
- Represent template primitives and pins internally as maps keyed by name, then lower to lists after merge. This avoids list patch complexity in the first iteration.
- Store resolved component type/options in `ComponentIR` and `design.metadata["dsl_chain"]`.
- Add a small proof-of-concept template, not full `TransmonPocket` parity yet.

Recommended short-term tests:

- `type + options` expands to same primitives as current hand-written example.
- Template default used when option omitted.
- Instance option override changes geometry.
- Unknown option key is rejected.
- Template primitive/pin maps merge by name.
- Metadata contains resolved type/options.
- `class: TransmonPocket` remains rejected.

Do not rush:

- Do not delete `qlibrary`.
- Do not add a full package manager for templates.
- Do not add a broad expression language.
- Do not introduce hidden qlibrary fallback.
- Do not promise Hamiltonian simulation semantics yet.
- Do not add role-rich netlist schema until template expansion is stable.

### Medium Term

Migrate a minimal `TransmonPocket`-like template in stages.

Stage 1: static transmon pocket:

- options for `pos_x`, `pos_y`, `orientation`, `chip`, `layer`
- `pad_width`, `pad_height`, `pad_gap`
- `pocket_width`, `pocket_height`
- `inductor_width` or `junction_width`
- generated pad top/bottom, pocket subtract, junction

Stage 2: connection pads:

- `connection_pads` as a map keyed by pad name
- `_default_connection_pads` equivalent as template defaults
- per-pad overrides merge with defaults
- generated connector pad poly
- generated connector wire path
- generated subtract path
- generated pin

Stage 3: ports and metadata:

- pin interface declaration in template
- pin roles such as drive/readout/coupling
- stable generated qgeometry names
- optional circuit defaults
- optional Hamiltonian defaults

Stage 4: parity tests:

- Generate a qlibrary `TransmonPocket` in a test design.
- Generate YAML `transmon_pocket` with equivalent options.
- Compare qgeometry table presence, row names where practical, pin names, pin widths, bounds, and selected path lengths.
- Do not require bit-for-bit shapely equality at first; use tolerances and semantic checks.

### Long Term

Move more qlibrary behavior into YAML-native templates and helper generators:

- simple primitives/components first
- common qubits next
- couplers/connectors after stable pin/port semantics
- routes last, because routing often needs path-finding, obstacles, anchors, lead lengths, and renderer-specific behavior

Long-term architecture should have:

- template schemas with versions
- local template imports
- built-in template registry
- option schemas and defaults
- deterministic merge/override policy
- constrained expression evaluator with units
- helper functions for common geometry construction
- generated port/pin interface contracts
- circuit/Hamiltonian contribution hooks
- metadata with raw source, resolved options, generated IR, derived data, and export net IDs

The Python qlibrary can remain as legacy/reference while YAML-native coverage grows. Removal should be an end-state discussion, not a near-term implementation task.

## 6. Risks, Test Gaps, And Architecture Traps

### Default Inheritance

Risk:

- `_deep_merge` recursively merges maps but replaces lists. This makes qlibrary-like overrides verbose and fragile.
- Current templates cannot express "inherit all pads, override only `readout.loc_W`".
- Current code has no distinction between template default, design default, instance override, and API override.

Recommendation:

- Use maps for override-heavy structures: primitives, pins, connection pads, ports.
- Lower maps to ordered lists only after resolution.
- Define precedence early:
  1. template parent defaults
  2. template defaults
  3. design defaults by type
  4. instance options
  5. API overrides
- Store enough provenance to explain resolved values.

### Expression Evaluation

Risk:

- Current interpolation is text substitution. Numeric parsing is deferred to `parse_value`.
- This works for simple strings such as `"${bus_y} - 6um"` only because the substituted string later reaches unit parsing.
- It is not a general expression system.
- It may behave differently across fields because not every field is parsed the same way.

Recommendation:

- Formalize where arithmetic is allowed.
- Keep the evaluator constrained to numeric/unit expressions and whitelisted helpers.
- Add tests for arithmetic in center, size, points, width, gap, layer, transforms, and template options.
- Reject ambiguous nonnumeric expressions with clear errors.

### Primitive Combination

Risk:

- Current primitives are too low-level for qlibrary ergonomics.
- Manual rectangle/path lists will become large and hard to maintain.
- `TransmonPocket` connection pads need generated geometry from named options.
- Pins often need to be derived from geometry edges/path segments, not hand-authored points.

Recommendation:

- Add helpers incrementally:
  - rectangle centered or anchored
  - line/path from points
  - edge pin from primitive/side
  - pin from last path segment
  - mirrored/rotated connection pad helper
- Keep helpers deterministic and testable.
- Avoid a generic Python escape hatch in YAML unless explicitly needed later.

### Pins And Netlist

Risk:

- Netlist currently allows only `{from, to}` and rejects metadata. That is good for strict v3, but roles/types will be needed.
- Endpoint reuse is rejected globally. This may be too strict for future multi-pin/multi-net scenarios, but it is acceptable for the current slice.
- Current `net_id` is added by mutating `ir.derived["netlist"]["connections"]` during export. That means IR after export differs from IR before export.

Recommendation:

- Keep current strict netlist for now.
- When roles are added, do it as a schema evolution with tests.
- Consider separating pre-export derived data from export results, or explicitly document that `export_ir_to_metal` enriches derived netlist entries with `net_id`.
- Add tests for metadata after export, including `net_id`.

### Circuit And Hamiltonian Consistency

Risk:

- Current Hamiltonian and circuit sections are arbitrary mappings.
- There is no validation that Hamiltonian subsystem names match component names.
- There is no validation that netlist components match circuit components.
- There is no validation that geometry components match circuit components.
- There is no conflict handling between circuit parameters and geometry options.

Recommendation:

- Add optional consistency checks:
  - circuit component names should match or intentionally reference geometry components.
  - Hamiltonian subsystem names should match circuit components where model requires it.
  - netlist endpoints should reference generated pins, already done.
- Add a clear precedence model before allowing both circuit and geometry options to set the same physical parameter.
- Start with warnings or explicit opt-in validation if backward compatibility is a concern.

### Metadata Model

Risk:

- `design.metadata["dsl_chain"]` currently stores resolved data, not the complete raw source.
- Future users will need to debug inherited defaults and generated primitives.
- Without raw/resolved separation, round-trip editing will be difficult.

Recommendation:

- Store:
  - raw source or source path/checksum
  - resolved document
  - resolved component options
  - generated primitive/pin IR
  - derived geometry
  - export results such as net IDs

### Renderer And Metal Core Compatibility

Risk:

- `NativeComponent.component_metadata` currently advertises `poly`, `path`, and `junction`.
- Future tables/options may need more generic handling.
- Export bypasses `QComponent.add_qgeometry` and calls `design.qgeometry.add_qgeometry` directly, which is intentional but may bypass component-level behavior users expect.
- Renderer defaults are deliberately not injected in current tests; that is good, but future templates may need renderer-specific options.

Recommendation:

- Keep direct qgeometry export for now.
- Add renderer-focused smoke tests later.
- Decide how table usage and renderer options are represented in YAML templates.

### Current Worktree State

At evaluation time, the worktree had an uncommitted modification in `design_dsl.py`: Chinese explanatory comments around `build_ir()`. I treated that as unrelated user/agent work and did not change it.

Test attempts:

- `pytest tests/test_design_dsl.py -q` failed because project `addopts` includes `--rich`, and this shell did not have the required pytest support.
- `pytest tests/test_design_dsl.py -q -o addopts=` failed before tests ran because `qiskit_metal.__init__` could not find installed distribution metadata for `quantum-metal`.
- With `PYTHONPATH=src`, collection still failed at the same package metadata requirement.

So I did not get a clean local test run in this shell. The failure points appear to be environment/setup issues, not direct DSL assertion failures.

## Recommended Next Slice

Implement this next:

1. Add component `type` and `options`.
2. Add one local template format with defaults and primitive/pin maps.
3. Resolve local option scope.
4. Expand into current `ComponentIR`.
5. Preserve the current primitive exporter.
6. Add a minimal `transmon_pocket` proof-of-concept template with no hidden qlibrary usage.

Acceptance criteria:

- The old hand-authored `chain_2q_native.metal.yaml` can be rewritten so `Q1` and `Q2` do not repeat primitive lists.
- Changing `Q2.options.pad_width` changes only Q2 geometry.
- Unknown option keys are rejected.
- Generated pins can be connected by the existing netlist.
- Metadata records component type and resolved options.
- `class: TransmonPocket` remains rejected.

This is the smallest useful bridge from primitive-only v3 toward YAML-native qlibrary replacement.
