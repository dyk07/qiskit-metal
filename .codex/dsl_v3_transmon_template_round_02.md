# DSL v3 Transmon Template Round 02

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 2

## Slice Chosen

Added the component template model and registry foundation, without adding
TransmonPocket-specific Python behavior.

This follows the recommended Round 2 slice from the progress file. I did not
repeat the Round 1 facade split work.

## Initial State

Command run first:

```text
git status --short
```

Initial status:

```text
 M src/qiskit_metal/toolbox_metal/design_dsl.py
?? .codex/
?? docs/dev_notes/
?? src/qiskit_metal/toolbox_metal/dsl/
```

The modified facade and untracked `dsl/` package were Round 1 work. The
untracked `.codex/` and `docs/dev_notes/` directories were preserved.

## Changes Made

- Added `src/qiskit_metal/toolbox_metal/dsl/errors.py`.
  - `DesignDslError` now lives in a shared module so builder and template
    infrastructure use the same exception class.
- Added `src/qiskit_metal/toolbox_metal/dsl/template_model.py`.
  - Defines `TEMPLATE_SCHEMA`.
  - Defines the `ComponentTemplate` dataclass.
  - Validates the minimum component-template schema:
    - `schema`
    - `id`
    - `extends`
    - `options`
    - `metadata`
    - `merge_rules`
    - `geometry.primitives`
    - `geometry.pins`
- Added `src/qiskit_metal/toolbox_metal/dsl/template_registry.py`.
  - Defines `ComponentTemplateRegistry`.
  - Adds built-in template id mapping for:
    - `qcomponent`
    - `base_qubit`
    - `transmon_pocket`
  - Supports inline template lookup from `geometry.templates` / root
    `templates`.
  - Supports file-template lookup relative to the design file directory.
  - Rejects unknown template types and inheritance cycles.
  - Built-in YAML files themselves are not added in this round; requesting one
    before the later YAML-template rounds gives a clear "not available yet"
    error.
- Added `src/qiskit_metal/toolbox_metal/dsl/component_templates.py`.
  - Expands component `type` + `options` into the existing primitive-only IR
    input shape.
  - Applies parent-to-child template inheritance.
  - Merges default options with instance overrides.
  - Rejects unknown option keys.
  - Records template metadata, resolved type, resolved options, selected
    template id, and inherited chain.
- Updated `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
  - Imports shared `DesignDslError`.
  - Accepts component keys `type` and `options`.
  - Adds `ComponentIR` fields:
    - `type`
    - `options`
    - `template`
    - `inherited`
  - Expands typed components before primitive and pin parsing.
  - Adds local interpolation roots for template expansion:
    - `component`
    - `options`
  - Keeps exporter primitive-only. The exporter still consumes only
    `PrimitiveIR` and `PinIR` rows and instantiates only `NativeComponent`.
  - Allows interpolation in mapping keys, which is needed for future generated
    primitive names.
- Updated `src/qiskit_metal/toolbox_metal/dsl/__init__.py`.
  - Re-exports template model/registry public helpers for later rounds.
- Added `tests/test_design_dsl_templates.py`.
  - Covers a trivial template producing one rectangle and one pin.
  - Covers instance option overrides.
  - Covers resolved type/options/template metadata in IR and exported design
    metadata.
  - Covers unknown template type rejection.
  - Covers unknown option rejection.
  - Covers parent/child template inheritance and option merge.

## Verification

New template test:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
5 passed, 4 warnings in 7.62s
```

Primitive-only regression plus new template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
74 passed, 4 warnings in 8.03s
```

Existing demo:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
```

Result:

```text
schema       : qiskit-metal/design-dsl/3
components   : ['Q1', 'Q2', 'bus']
poly rows    : 6
path rows    : 2
junction rows: 2
net rows     : 4
derived keys : ['circuit', 'netlist']
PASS: native DSL chain exported to Metal
```

## Current State After Round

Status after edits:

```text
 M src/qiskit_metal/toolbox_metal/design_dsl.py
?? .codex/
?? docs/dev_notes/
?? src/qiskit_metal/toolbox_metal/dsl/
?? tests/test_design_dsl_templates.py
```

Notes:

- `design_dsl.py` remains the Round 1 facade and was not otherwise changed in
  this round.
- `docs/dev_notes/` remains untracked and untouched.
- No qlibrary `TransmonPocket` class is imported or instantiated by the new
  template path.

## Remaining Work

Recommended next round:

Add safe expression/local context support for arithmetic and unit expressions.
The current interpolation still supports simple `${root.path}` replacement; it
does not yet evaluate expressions such as
`${(options.pad_height + options.pad_gap) / 2}`.

Later rounds should add:

- generic geometry operation registry
- normal-segment pin mode
- `qcomponent.yaml`
- `base_qubit.yaml`
- `transmon_pocket.yaml`
- connection-pad generator support
- two-transmon example and parity tests
