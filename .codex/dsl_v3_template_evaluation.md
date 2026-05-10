# Native v3 DSL Template Evaluation

Date: 2026-05-11

Scope checked lightly:

- `src/qiskit_metal/toolbox_metal/design_dsl.py`
- `examples/dsl/README.md`
- `examples/dsl/chain_2q_native.metal.yaml`
- `examples/dsl/native_2q_minimal.metal.yaml`
- `tests/test_design_dsl.py`

No core code was modified for this evaluation.

## Short Conclusion

The current native v3 DSL is a useful primitive-first proof of concept: it can load YAML, expand simple includes/templates/loops, resolve interpolation, build primitive/pin IR, and export directly to Metal qgeometry/pins/netlist without instantiating qlibrary component classes. It is not yet a real replacement for `src/qiskit_metal/qlibrary` templates such as `TransmonPocket`, because it lacks a YAML-native component type system with stable option schemas, named defaults, nested option inheritance, parametric pad/coupler generation, and bidirectional Hamiltonian/Circuit/Netlist/Geometry propagation.

The correct direction is not to "remove TransmonPocket" as a library dependency while keeping equivalent Python classes elsewhere. The real target is to stop using `src/qiskit_metal/qlibrary` Python classes as the DSL construction target, and gradually replace qlibrary templates with YAML component templates that expand into primitives, pins, derived metadata, and optional circuit/Hamiltonian defaults.

## Current v3 State

What works now:

- Schema gate: `qiskit-metal/design-dsl/3`.
- Root sections: `vars`, `hamiltonian`, `circuit`, `netlist`, `geometry`, `templates`.
- YAML duplicate-key rejection.
- `$include` for including a whole mapping node from another YAML file.
- `$extend` for deep-merging a template mapping into a node.
- `$for` expansion for repeated items.
- Dotted interpolation such as `${vars.pad_w}`, `${circuit.Q1.pad_width}`.
- Primitive generation for:
  - `poly.rectangle`
  - `poly.polygon`
  - `path.line`
  - `path.polyline`
  - `junction.line`
- Component-level and item-level transforms: translate, rotate, origin.
- Explicit pins with width/gap/chip.
- Basic netlist endpoint validation and `design.connect_pins`.
- Export through `NativeComponent`, writing rows directly to `design.qgeometry`.
- Metadata round-trip into `design.metadata["dsl_chain"]`.
- Derived geometry summary: primitive bounds, path lengths, pin middles, resolved netlist connections.

The examples demonstrate a hand-written two-transmon sketch and a small template `transmon_pad_pair`. The tests cover many useful parser/export constraints: duplicate names, typo rejection, bad netlist endpoints, unknown chips, transform errors, include cycles, boolean parsing, and qlibrary class rejection.

## Gap Versus Replacing qlibrary Templates

The current implementation is still "primitive reuse", not "component template reuse".

Important gaps:

- No first-class component template file format. Existing `templates` are anonymous YAML fragments mixed into the design document or included as a whole mapping.
- No component type identity such as `type: qiskit_metal/transmon_pocket`. `$extend: transmon_pad_pair` is just a structural merge.
- No option schema. There is no list of valid component options, defaults, required options, documentation, units, enum constraints, nested option groups, or deprecated aliases.
- No key-name inheritance contract. A YAML template can provide keys, but an editor cannot reliably know which keys are inherited defaults, user overrides, generated keys, optional pad names, or legal extension points.
- List merge semantics are too weak for qlibrary-style defaults. `_deep_merge` replaces lists wholesale, so overriding one pad or one primitive requires repeating the whole list. That is already visible in `chain_2q_native.metal.yaml`: `Q2` repeats every primitive just to change `circuit.Q2.pad_width` and pin direction.
- Interpolation is global and text-based. Templates currently hard-code paths such as `${circuit.Q1.pad_width}`. A reusable component template needs local option references such as `${options.pad_width}` or `${component.options.pad_width}`, then each instance can bind options without embedding instance names.
- No nested generated structures for connection pads/couplers. `BaseQubit`/`TransmonPocket` behavior around `connection_pads`, pad-specific defaults, and pins is not represented as a general mechanism.
- No template-generated circuit or Hamiltonian defaults. Current downward flow is mostly user-written `circuit -> geometry`; upward flow is only `derived.circuit.geometry`. A YAML template cannot yet say "this component contributes circuit defaults, Hamiltonian defaults, pin roles, port capacitance hints, junction symbols, or coupling metadata".
- No symbolic geometry expressions beyond simple value substitution and primitive constructors. Qlibrary templates often use formulas and conditional geometry assembly, not only static rectangles.
- No array/dictionary patch operations. This blocks ergonomic overrides like "inherit all default connection pads, but override `readout.loc_W` and add `drive`".
- No template package/discovery path. Future YAML qlibrary equivalents need predictable locations, import names, versioning, and dependency resolution.
- No validation that template-generated pins match declared interface contracts.
- No tests for external template libraries, component defaults, local option scope, list item patching, generated pad maps, or circuit/Hamiltonian propagation from templates.

## Proposed YAML-Native Component/Template Mechanism

### File Types

Keep design files separate from reusable component template files.

Design file:

```yaml
schema: qiskit-metal/design-dsl/3

imports:
  transmon_pocket: qiskit_metal.templates.qubits.transmon_pocket@1

geometry:
  design: {class: DesignPlanar}
  components:
    Q1:
      type: transmon_pocket
      options:
        pos_x: -1.2mm
        connection_pads:
          readout:
            loc_W: 1
            pad_width: 125um
    Q2:
      type: transmon_pocket
      options:
        pos_x: 1.2mm
        connection_pads:
          readout:
            loc_W: -1
```

Template file:

```yaml
schema: qiskit-metal/component-template/1
id: qiskit_metal.templates.qubits.transmon_pocket
kind: component
version: 1
extends: null

interface:
  pins:
    readout:
      role: coupling
      generated_from: options.connection_pads.readout
  qgeometry_tables: [poly, path, junction]

options:
  pos_x: 0mm
  pos_y: 0mm
  orientation: 0deg
  chip: main
  layer: 1
  pad_width: 455um
  pad_height: 90um
  pad_gap: 30um
  pocket_width: 650um
  pocket_height: 650um
  junction_width: 10um
  connection_pads:
    readout:
      loc_W: 1
      loc_H: 0
      pad_width: 125um
      pad_height: 30um
      pad_gap: 15um
      pin_width: 10um
      pin_gap: 6um

geometry:
  transform:
    translate: ["${options.pos_x}", "${options.pos_y}"]
    rotate: "${options.orientation}"
  primitives:
    - name: pocket
      type: poly.rectangle
      center: [0mm, 0mm]
      size: ["${options.pocket_width}", "${options.pocket_height}"]
      subtract: true
      layer: "${options.layer}"
      chip: "${options.chip}"
    - name: pad_left
      type: poly.rectangle
      center: ["-${options.pad_gap}/2 - ${options.pad_width}/2", 0mm]
      size: ["${options.pad_width}", "${options.pad_height}"]
      layer: "${options.layer}"
      chip: "${options.chip}"
    - name: pad_right
      type: poly.rectangle
      center: ["${options.pad_gap}/2 + ${options.pad_width}/2", 0mm]
      size: ["${options.pad_width}", "${options.pad_height}"]
      layer: "${options.layer}"
      chip: "${options.chip}"
    - name: jj
      type: junction.line
      points: [[0mm, "-${options.pad_height}/2"], [0mm, "${options.pad_height}/2"]]
      width: "${options.junction_width}"
      layer: "${options.layer}"
      chip: "${options.chip}"

generators:
  connection_pads:
    for_each: "${options.connection_pads}"
    as: pad
    primitives:
      - name: "cp_${pad.key}_metal"
        type: poly.rectangle
        center: ["${pad.value.loc_W} * ${options.pocket_width}/2", "${pad.value.loc_H} * ${options.pocket_height}/2"]
        size: ["${pad.value.pad_width}", "${pad.value.pad_height}"]
        layer: "${options.layer}"
        chip: "${options.chip}"
    pins:
      - name: "${pad.key}"
        points: "edge_pin(cp_${pad.key}_metal, side=${pad.value.loc_W}, width=${pad.value.pin_width})"
        width: "${pad.value.pin_width}"
        gap: "${pad.value.pin_gap}"
        chip: "${options.chip}"

circuit:
  defaults:
    type: transmon
    junction: "${component.name}.jj"
    pads: "${options.connection_pads}"

hamiltonian:
  defaults:
    model: transmon
```

This syntax is illustrative, not final. The important design point is that component templates expose an `options` dictionary and expand using local `options`, not hard-coded `circuit.Q1` paths.

### Defaults and Overrides

Resolution order should be explicit:

1. Template inheritance chain defaults.
2. Template `options`.
3. Design-level defaults by type, for example `geometry.defaults.transmon_pocket`.
4. Instance `options`.
5. CLI/API `overrides`.

Deep merge should be map-aware and list-aware:

- Mapping keys merge recursively.
- Scalars replace.
- Lists should support keyed merge for lists of named objects, or avoid lists for override-heavy structures.
- For qlibrary-style components, prefer dictionaries keyed by stable names for primitives, pins, pads, and couplers, then lower to ordered lists after resolution.

Recommended component-source shape after resolution:

```yaml
component:
  name: Q1
  type: transmon_pocket
  options:
    pad_width: 455um
    connection_pads:
      readout:
        loc_W: 1
        pin_width: 10um
  inherited:
    template: qiskit_metal.templates.qubits.transmon_pocket@1
    keys:
      pad_width: default
      connection_pads.readout.loc_W: override
```

The `inherited.keys` map is useful for editors, diagnostics, and explaining where defaults came from.

### Key Name Inheritance

Templates should define a schema for option keys:

```yaml
schema:
  options:
    pad_width: {type: length, default: 455um}
    orientation: {type: angle, default: 0deg}
    connection_pads:
      type: map
      values:
        loc_W: {type: int, default: 1}
        loc_H: {type: int, default: 0}
        pin_width: {type: length, default: 10um}
```

Minimum viable implementation can start with defaults-only and unknown-key rejection. Later it can add documentation, units, enums, aliases, and deprecation warnings.

Editor behavior then becomes possible:

- Load design instance `type`.
- Resolve template inheritance.
- Show inherited option keys and default values.
- Let user override only the specific keys they need.
- Preserve unknown-key rejection for typos.

### Geometry Primitive Generation

Keep the exporter primitive-only. The new layer should expand YAML component templates into the existing `ComponentIR` with `PrimitiveIR` and `PinIR`.

Needed enhancements:

- Local expression context:
  - `${component.name}`
  - `${options.*}`
  - `${vars.*}`
  - `${circuit.*}`
  - `${hamiltonian.*}`
  - generator locals such as `${pad.key}`, `${pad.value.*}`
- Expression evaluation for simple arithmetic with units. Today strings like `"${bus_y} - 6um"` work only because `parse_value` later sees a substituted expression. This should be formalized and tested for all numeric fields.
- More primitive types and helper constructors:
  - rounded rectangles or rectangle plus fillet
  - polygons from named points
  - route/path helpers
  - edge-pin helpers
  - anchor/port helpers
- Dict-based primitive and pin declarations at template time, lowered to lists with stable names after expansion.

### Pins, Netlist, Circuit, Hamiltonian Propagation

Downward flow:

- Global `vars` and design-level defaults feed template options.
- Circuit/Hamiltonian sections may override or bind component options.
- Component options generate geometry primitives and pins.
- Netlist connects generated pins.

Upward flow:

- Geometry derives bounds, path lengths, pin middles, junction lengths, areas, and anchors.
- Component templates can publish selected derived data back to `circuit` and/or `hamiltonian`.
- Exported `design.metadata["dsl_chain"]` should retain:
  - unresolved source
  - resolved component options
  - inherited key/default provenance
  - generated primitives/pins
  - derived geometry summary
  - net IDs after export

Recommended resolved IR additions:

```python
ComponentIR:
    type: str | None
    options: dict
    inherited: dict
    ports: dict
    circuit_defaults: dict
    hamiltonian_defaults: dict
```

Netlist should support endpoint roles eventually:

```yaml
netlist:
  connections:
    - from: Q1.readout
      to: bus.start
      role: readout
```

The current tests reject extra connection keys. That is good for v3 strictness, but role/type metadata will need a schema evolution or a permitted key addition.

### TransmonPocket-Like Defaults

A YAML `transmon_pocket` template should map the important Python defaults directly:

- Main options:
  - chip
  - layer
  - pos_x / pos_y
  - orientation
  - pad_width
  - pad_height
  - pad_gap
  - pocket_width
  - pocket_height
  - inductor_width or junction_width
  - subtract flags
- Junction:
  - named primitive `jj`
  - table `junction`
  - width and endpoints derived from pad geometry
  - optional circuit/Hamiltonian binding
- Pads/couplers:
  - `connection_pads` as a map keyed by pad name
  - each pad inherits default pad dimensions, gap, pin width/gap, location, lead length, and orientation
  - generator produces both metal/cut primitives and a pin with the same stable key
- Defaults are inherited at pad-key level:
  - User can define `connection_pads.readout.loc_W: 1`.
  - Missing keys come from the pad default schema.
  - New pads can be added by adding new map entries.

This is the core mechanism that would make a `.yaml` template feel like `TransmonPocket.default_options` without importing `TransmonPocket`.

## Minimal Code Path

Phase 0: keep current v3 stable.

- Do not reintroduce qlibrary classes as construction targets.
- Keep primitive export via `NativeComponent`.
- Keep typo rejection and duplicate-key rejection.

Phase 1: add component template loading without changing primitive exporter.

- Add root `imports` or `template_paths`.
- Add template-file schema `qiskit-metal/component-template/1`.
- Add resolver that maps `type: transmon_pocket` to a template.
- Add local option context and resolved `ComponentIR.type/options/inherited`.
- Expand component templates into the existing `primitives` and `pins`.
- Tests:
  - template file import
  - instance `type + options`
  - default inheritance
  - unknown option rejection
  - override provenance in metadata

Phase 2: fix override semantics.

- Represent template primitives/pins/pads as dictionaries keyed by name before lowering.
- Add a keyed merge strategy or explicit patch operations:
  - `$delete`
  - `$replace`
  - `$append`
  - `$merge_by: name`
- Tests for overriding one primitive, one pin, and one connection pad without repeating whole lists.

Phase 3: add generators for qlibrary-like nested structures.

- Implement `for_each` over maps such as `options.connection_pads`.
- Add generator-local variables.
- Add helper functions for edge pins, anchors, side selection, mirrored pad placement, and maybe route skeletons.
- Tests for two connection pads with inherited defaults and per-pad overrides.

Phase 4: add template contributions to circuit/Hamiltonian/netlist metadata.

- Let component templates publish `circuit.defaults` and `hamiltonian.defaults`.
- Merge these with user-authored top-level sections in a deterministic order.
- Preserve both raw user data and generated/resolved data in metadata.
- Consider allowing netlist connection metadata such as `role`.

Phase 5: migrate qlibrary templates gradually.

- Start with a small, high-value YAML template:
  - `transmon_pocket.yaml`
  - maybe a simple cpw/route template
- Keep Python qlibrary in the repo during migration.
- Add parity examples/tests comparing generated qgeometry/pin names against known qlibrary outputs where practical.
- Migrate templates one by one:
  - qubits first
  - simple couplers/connectors
  - routes last, because routing behavior often needs more helpers

## Current Design Issues and Test Gaps

Observed design issues:

- `$extend` with list fields replaces lists, which makes template overrides verbose and fragile.
- The `transmon_pad_pair` example hard-codes `${circuit.Q1.pad_width}`, so it is not reusable as a real component template. `Q2` repeats primitives to work around this.
- `templates` are untyped fragments. There is no difference between component templates, primitive templates, and pin templates.
- No local `options` namespace for component instances.
- No first-class template import/discovery/versioning.
- No option-schema validation.
- No provenance of inherited defaults versus user overrides.
- No generator mechanism for maps such as `connection_pads`.
- `netlist.connections` is intentionally minimal and rejects any metadata; this will need evolution for circuit roles.
- Primitive support is too small for qlibrary parity.
- `NativeComponent.component_metadata` advertises only `path`, `poly`, and `junction`; future primitive tables or renderer-specific options need a generic strategy.
- Current comments in `build_ir` are Chinese study notes in the development worktree. That may be intentional from another agent/user, but they are implementation comments in active dev code rather than docs. I did not touch them.

Test gaps to add:

- External component-template file import.
- Template inheritance across files.
- Component `type` with local `options`.
- Unknown option-key rejection.
- Default provenance in `ir.geometry` or metadata.
- Map-based connection pad inheritance.
- Override one pad without repeating all pads.
- Override one primitive without repeating all primitives.
- Template-generated pins validated against interface declarations.
- Generated circuit/Hamiltonian defaults and user override precedence.
- Netlist metadata/role behavior once introduced.
- Expression evaluation with arithmetic and units across all numeric fields.
- Round-trip metadata for resolved source, generated components, and net IDs.

## Recommended Immediate Decision

Do not market current primitive-only v3 as "replacing TransmonPocket" yet. It replaces direct qlibrary class instantiation in the DSL examples, but not the qlibrary template capability.

The next useful implementation slice is a YAML component template resolver that:

1. imports one external template file,
2. supports `type` plus `options`,
3. resolves inherited defaults with provenance,
4. expands to the current primitive/pin IR,
5. includes a minimal `transmon_pocket.yaml` proof of concept with one generated `connection_pads` entry.

That slice preserves the current exporter and gives a clear bridge from qlibrary Python templates to YAML-native templates.
