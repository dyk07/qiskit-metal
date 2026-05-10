# DSL v3 Transmon Template Round 01

Date: 2026-05-11

Worker: DSL v3 Transmon YAML template loop worker, round 1

## Slice Chosen

Baseline plus first package facade split for `design_dsl.py`, with no intended behavior change.

This matches the recommended Round 1 slice from the progress file. I kept the scope deliberately narrow because `src/qiskit_metal/toolbox_metal/design_dsl.py` already had uncommitted user/agent edits.

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
```

The existing `design_dsl.py` modification was a small set of Chinese learning comments around `build_ir()` load/include preprocessing. I preserved those comments by moving the current implementation into the new package module.

## Changes Made

- Added `src/qiskit_metal/toolbox_metal/dsl/`.
- Added `src/qiskit_metal/toolbox_metal/dsl/builder.py`.
  - This contains the previous `design_dsl.py` implementation, including the pre-existing Chinese study comments.
- Added `src/qiskit_metal/toolbox_metal/dsl/__init__.py`.
  - Re-exports the public DSL API from `builder.py`.
- Replaced `src/qiskit_metal/toolbox_metal/design_dsl.py` with a backward-compatible facade.
  - Existing imports from `qiskit_metal.toolbox_metal.design_dsl` continue to work.
  - `CURRENT_SCHEMA` is also exported, matching current tests and practical usage.

This round did not add component template features, TransmonPocket behavior, or template-specific Python logic.

## Verification

Baseline/test command confirmed with the configured conda Python:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py -q
```

Result:

```text
69 passed, 4 warnings in 8.29s
```

Demo command:

```text
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples/dsl/run_chain_demo.py
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
```

Notes:

- `.codex/` existed before this round as an untracked directory. This round added `.codex/dsl_v3_transmon_template_round_01.md` and updated the progress file inside it.
- `docs/dev_notes/` was already untracked and was not touched.
- `design_dsl.py` is now 33 lines.
- `dsl/builder.py` is 981 lines.

## Remaining Work

The package split is only the compatibility/facade baseline. Later rounds should split `builder.py` into the planned focused modules:

- `errors.py`
- `schema.py`
- `ir.py`
- `yaml_io.py`
- `expansion.py`
- `expression.py`
- `primitives.py`
- `pins.py`
- `netlist.py`
- `derive.py`
- `design_factory.py`
- `exporter.py`

Recommended next round:

Add the component template model/registry foundation without TransmonPocket-specific behavior, or first continue mechanical module extraction if reviewers prefer a more literal split before template work.

