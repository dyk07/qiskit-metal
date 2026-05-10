# DSL v3 Transmon Template Round 03

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 3

## Slice Chosen

Added safe expression and local context support needed by YAML component
templates.

This follows the recommended Round 3 slice from the progress file. I did not
repeat the Round 1 package facade work or the Round 2 template model/registry
work.

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
?? tests/test_design_dsl_templates.py
```

The modified facade, untracked DSL package, and template test file were prior
round work. The untracked `docs/dev_notes/` directory was preserved and not
touched.

## Changes Made

- Added `src/qiskit_metal/toolbox_metal/dsl/expression.py`.
  - Provides `resolve_path()`, `evaluate_expression()`,
    `substitute_string()`, and `walk_substitute()`.
  - Keeps old dotted-path interpolation behavior for expressions such as
    `${vars.pad_w}` and `${options.width}`.
  - Adds constrained expression evaluation for arithmetic needed by future
    templates:
    - binary `+`, `-`, `*`, `/`
    - unary `+`, `-`
    - parentheses through Python AST parsing
    - dotted local context paths such as `options.pad_height`
    - numeric literals with Metal units such as `1um`, `30um`, `1e3nm`
    - numeric strings from context, parsed through Metal `parse_value`
  - Rejects unsupported expression syntax such as function calls.
  - Returns the evaluated object for strings that are exactly one
    interpolation expression, while embedded interpolations remain string
    substitutions. This preserves legacy usage such as `-${vars.qx}`.
- Updated `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
  - Replaced the previous local `_walk_substitute()` implementation with the
    new shared expression helper.
  - Existing primitive-only interpolation, `$include`, `$extend`, `$for`,
    template expansion, design/circuit/hamiltonian/netlist substitution, and
    geometry parsing now use the same expression path.
  - The exporter remains primitive-only and still instantiates only
    `NativeComponent`.
- Updated `src/qiskit_metal/toolbox_metal/dsl/__init__.py`.
  - Re-exports `evaluate_expression`, `substitute_string`, and
    `walk_substitute` for later package/module split work.
- Updated `tests/test_design_dsl_templates.py`.
  - Added coverage for template-local arithmetic and unit expressions:
    `${(options.pad_height + options.pad_gap) / 2}`,
    `${2 * options.trace_width}`,
    `${-options.trace_width / 2}`, and `${options.pad_height / 3}`.
  - Added coverage for local roots:
    - `vars`
    - `circuit`
    - `hamiltonian`
    - `netlist`
    - `component`
    - `options`
  - Added rejection tests for unknown names and unsupported expression syntax.

## Verification

New template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl_templates.py -q
```

Result:

```text
8 passed, 4 warnings in 8.11s
```

Primitive-only regression plus template tests:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q
```

Result:

```text
77 passed, 4 warnings in 8.52s
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

- `design_dsl.py` remains the Round 1 facade and was not changed in this
  round.
- `docs/dev_notes/` remains untracked and untouched.
- No TransmonPocket-specific formulas or option defaults were added to Python.
- No qlibrary `TransmonPocket` class is imported or instantiated by this
  expression/template path.

## Remaining Work

Recommended next round:

Add the generic geometry operation registry. The expression support added in
this round should be enough for operation fields such as rectangle dimensions,
polyline points, buffer distances, transform offsets, and future generator
locals.

Later rounds should add:

- generic geometry operation registry
- normal-segment pin mode
- `qcomponent.yaml`
- `base_qubit.yaml`
- `transmon_pocket.yaml`
- connection-pad map-entry inheritance
- connection-pad generator support
- two-transmon example and parity tests
