# DSL v3 Transmon Template Implementation Progress

Plan:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main\.codex\dsl_v3_transmon_template_final_implementation_plan.md`

Worktree:

`D:\BaiduSyncdisk\vsCOde\circuit\qiskit\qiskit-metal-worktrees\dyk07-main`

Python:

`C:\ProgramData\anaconda3\envs\metal-env\python.exe`

## Loop State

- Status: in_progress
- Current round: 3
- Completion: 26%
- Last updated by: worker-round-03
- Last updated at: 2026-05-11

## Stop Rules

The main agent should keep launching one worker subagent per round until one of these is true:

- Completion reaches 100%.
- Round count exceeds 16.
- Round count exceeds 10 and completion is still below 50%.

## Worker Protocol

Each worker must:

- Read this progress file first.
- Read the final implementation plan.
- Inspect local git status before editing.
- Choose a coherent slice that can be completed in this round.
- Preserve unrelated user or agent changes.
- Update this progress file before finishing.
- Write a detailed round report to `.codex/dsl_v3_transmon_template_round_XX.md`.
- Return to the main agent only the final completion percentage for the overall task.

Workers are not alone in the codebase. Do not revert edits made by users or other agents; adapt to the current worktree state.

## Recommended Round Slices

- Round 1: establish baseline status, split `design_dsl.py` into a package facade without behavior change, preserve tests.
- Round 2: add template model and registry, without TransmonPocket-specific Python behavior.
- Round 3: add safe expression/local context support needed by templates.
- Round 4: add generic geometry operation registry.
- Round 5: add pin modes needed for TransmonPocket, especially normal-segment pins.
- Round 6: add `qcomponent.yaml` and template inheritance foundation.
- Round 7: add `base_qubit.yaml` and map-entry inheritance for `connection_pads`.
- Round 8: add static `transmon_pocket.yaml` pocket geometry.
- Round 9: add YAML generator support for `connection_pads`.
- Round 10: add two-transmon example and README updates.
- Round 11: add parity/no-qlibrary-construction tests.
- Rounds 12-16: integration cleanup, bug fixes, parity gaps, documentation polish.

Workers may choose a different slice if the current repository state makes another slice more appropriate.

## Checklist

- [x] Baseline test command confirmed.
- [x] `design_dsl.py` is a facade only.
- [x] New `qiskit_metal.toolbox_metal.dsl` package exists.
- [x] Existing primitive-only v3 behavior still passes.
- [x] Template dataclasses/model added.
- [x] Built-in/file template registry added.
- [x] Template inheritance and option merge implemented.
- [x] Unknown template types/options are rejected.
- [x] Safe expression/local context support added.
- [ ] Generic geometry operation registry added.
- [x] Primitive exporter remains primitive-only.
- [ ] Pin parser supports tangent-point pins.
- [ ] Pin parser supports normal-segment pins.
- [ ] `qcomponent.yaml` added.
- [ ] `base_qubit.yaml` added.
- [ ] `transmon_pocket.yaml` added.
- [ ] `connection_pads` map-entry inheritance implemented.
- [ ] `connection_pads` generator implemented.
- [ ] Two-transmon template example added.
- [ ] README documents YAML-native templates.
- [x] Tests cover template expansion.
- [ ] Tests cover no qlibrary `TransmonPocket` instantiation.
- [ ] Tests cover generated pins and netlist connection.
- [ ] Tests cover TransmonPocket geometry row names.
- [x] Tests cover circuit/hamiltonian/netlist interpolation through templates.
- [x] `python -m pytest tests/test_design_dsl.py -q` passes with the conda Python.
- [x] `python examples/dsl/run_chain_demo.py` passes with the conda Python.

## Round Log

- Round 01: Established the conda Python baseline, moved the existing native DSL implementation into `src/qiskit_metal/toolbox_metal/dsl/builder.py`, added `dsl/__init__.py`, and reduced `design_dsl.py` to a backward-compatible public facade. Preserved the pre-existing Chinese study comments by carrying them into `builder.py`. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py -q` (`69 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples/dsl/run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_01.md`.
- Round 02: Added shared DSL errors, component template dataclass/schema validation, a template registry with inline/file/built-in lookup scaffolding, and generic `type` + `options` expansion into the existing primitive-only IR path. Added `ComponentIR` template fields and local `component`/`options` interpolation roots. Added template tests for expansion, overrides, inheritance, unknown types/options, metadata, and NativeComponent export. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`74 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_02.md`.
- Round 03: Added shared safe expression/interpolation helpers in `dsl/expression.py`, replacing the old dotted-path-only substitution path while preserving primitive-only behavior. Expressions now support local roots (`vars`, `circuit`, `hamiltonian`, `netlist`, `component`, `options`), numeric/unit arithmetic, unary operators, parentheses, typed full-string interpolation, and clear rejection of unknown names or unsupported syntax. Added template tests covering arithmetic and circuit/hamiltonian/netlist interpolation through templates. Verified with `C:\ProgramData\anaconda3\envs\metal-env\python.exe -m pytest tests/test_design_dsl.py tests/test_design_dsl_templates.py -q` (`77 passed, 4 warnings`) and `C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py` (`PASS: native DSL chain exported to Metal`). Detailed report: `.codex/dsl_v3_transmon_template_round_03.md`.
