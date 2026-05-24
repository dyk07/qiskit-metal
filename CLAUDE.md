# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this directory is

A git **worktree** of [qiskit-metal](https://github.com/qiskit-community/qiskit-metal) (Quantum Metal v0.5.3.post1), checked out on branch `full_chain`. The `.git` here is a pointer file → `../../qiskit-metal/.git/worktrees/dyk07-main`; both this worktree and the sibling `qiskit-metal/` study copy share the same object database.

Remotes:
- `origin`  → https://github.com/dyk07/qiskit-metal (user fork)
- `upstream` → https://github.com/qiskit-community/qiskit-metal

This worktree is the **active development copy** — new features and behavior changes go here. The sibling `qiskit-metal/` tree (on branch `main`) is for reading/study and Chinese learning annotations. See the parent `../../CLAUDE.md` for the workspace-wide layout.

Source lives under `src/qiskit_metal/` (uv build backend; `tool.uv.build-backend.module-name = "qiskit_metal"` keeps the legacy import path).

## Active feature on this branch: DSL v3

The `full_chain` branch is building a **native YAML DSL** that resolves a single `.metal.yaml` file into a Metal `QDesign` without going through qlibrary Python classes (no `TransmonPocket(...)` instantiation). Key entry points:

- `src/qiskit_metal/toolbox_metal/dsl/` — implementation:
  - `builder.py` — `build_ir(yaml)` parses YAML → `DesignIR` (primitives, pins, netlist, derived); `build_design(yaml)` exports the IR to a real `QDesign` (writes qgeometry tables, pins, calls `connect_pins`).
  - `component_templates.py` + `template_registry.py` + `template_model.py` — resolve `type: transmon_pocket` style component templates by walking the inheritance chain `qcomponent → base_qubit → transmon_pocket`.
  - `expression.py` — `${...}` interpolation and safe AST evaluation (uses `parsing.parse_value` for unit literals like `12um`, `1.2mm`, `18GHz`).
  - `geometry_ops.py` — shapely operations used by template-generated geometry.
  - `_helpers.py` — YAML loader (rejects duplicate keys), unit parsing, deep merge.
- `src/qiskit_metal/toolbox_metal/dsl_templates/` — built-in component YAML templates (`core/qcomponent.yaml`, `core/base_qubit.yaml`, `qubits/transmon_pocket.yaml`).
- `src/qiskit_metal/toolbox_metal/design_dsl.py` — thin backward-compat facade that re-exports the `dsl` package API.
- `examples/dsl/*.metal.yaml` + notebooks + `run_*_demo.py` smoke-test scripts (notebooks prepend `../../src` to `sys.path` so no install needed).
- `tests/test_design_dsl*.py` — three test files covering IR, templates, and the transmon_pocket parity case.
- `.codex/dsl_v3_*.md` — design-review notes from prior agent rounds. **Read-only context**; not generated files but not production code either.

Schema header for DSL files: `schema: qiskit-metal/design-dsl/3`. Top-level sections: `vars`, `hamiltonian`, `circuit`, `netlist`, `geometry` (with sub-keys `design`, `templates`, `components`, `transforms`). Component templates use `type:` and `options:`; primitive-native components use `primitives:` + `pins:` directly.

When editing the DSL: the schema is centralized as `CURRENT_SCHEMA` and the per-section allowed keys as `ROOT_KEYS`, `GEOMETRY_KEYS`, `DESIGN_KEYS`, `TRANSFORM_KEYS`, `COMPONENT_KEYS` at the top of `builder.py`. Update these together when adding YAML surface area.

## Running

This worktree uses `uv` + `tox` for dev tasks (configured in `pyproject.toml`, no separate `tox.ini`). Tests set `QISKIT_METAL_HEADLESS=1` so PySide6 windows do not pop up. CI matrix is Python 3.10/3.11/3.12 × ubuntu-24.04/macos-15/windows-2025.

```powershell
tox -m test                          # pytest across all configured Python versions
tox -e py3.12                        # one Python version
tox -e py3.12 -- tests/test_design_dsl.py::test_build_design_round_trip   # one test
tox -e lint                          # ruff check on qiskit_metal
tox -e format                        # ruff format on qiskit_metal
tox -e docs                          # sphinx HTML build
```

Demo scripts are run with the conda env that has Quantum Metal + PySide6 installed (the parent project's `.venv` is Python 3.13, which is **outside** the supported `>=3.10,<3.13` range — do not use it for these):

```powershell
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_chain_demo.py
C:\ProgramData\anaconda3\envs\metal-env\python.exe examples\dsl\run_transmon_pocket_demo.py
```

Notebooks in `examples/dsl/` open with the `metal-env` Jupyter kernel; they self-bootstrap `sys.path` to point at `src/`, so no `pip install` of this worktree is required to iterate on the DSL.

## qiskit-metal big-picture architecture (for orientation)

`src/qiskit_metal/` modules and how they fit together:

- `designs/` — `QDesign` and its subclasses (`DesignPlanar`, `DesignFlipChip`, `DesignMultiPlanar`). Owns `components` registry, `qgeometry` tables, `net_info`, chip metadata.
- `qlibrary/` — pre-built `QComponent`s (`qubits/`, `couplers/`, `lumped/`, `resonators/`, `sample_shapes/`, `terminations/`, `tlines/`, plus `core/` base classes and `user_components/`). The DSL v3 work deliberately bypasses this layer.
- `renderers/` — exporters (`QGDSRenderer`, `QAnsysRenderer`, `QHFSSRenderer`, `QQ3DRenderer`, `QPyaedt`, `QGmshRenderer`, `QElmerRenderer`) all extending `QRenderer`.
- `analyses/` — Hamiltonian / EPR / lumped-element / scattering / sweep helpers.
- `_gui/` — `MetalGUI` (PySide6; v0.5 dropped PySide2). Headless mode flag: `QISKIT_METAL_HEADLESS=1`.
- `toolbox_metal/` — Metal-specific utilities: `parsing.parse_value` (unit strings), `import_export`, `layer_stack_handler`, and the **DSL** (above).
- `toolbox_python/`, `draw/`, `qgeometries/` — generic helpers, drawing primitives, geometry-table layer.

`README_Architecture.md` has the upstream mermaid diagram and the contract for custom `QComponent` / `QRenderer` subclasses.

## Conventions

- **Language**: code under `src/qiskit_metal/` is English — this is the upstream dev tree and changes here are intended to flow upstream. The DSL example YAMLs, demo notebooks, and `.codex/` notes are user-authored extensions and use Chinese comments; keep that style when adding to those areas.
- **PySide binding**: PySide6 only. `qiskit_metal/__init__.py` sets `os.environ["QT_API"] = "pyside6"` at import time. Do not "fix" code to use PySide2.
- **Headless tests**: anything that touches `MetalGUI` must respect `QISKIT_METAL_HEADLESS`. `tox` env_run_base already sets it.
- **Ruff**: lint config is in `pyproject.toml` under `[tool.ruff.lint]` and is a deliberate work-in-progress (`E402, F401, F841, E731, F403, E712, E722, E741, F821` are currently ignored). Do not "clean up" violations of those rules wholesale — they are tracked tech-debt, not the current bar.
- **YAML DSL keys**: built-in template ids (`qcomponent`, `base_qubit`, `transmon_pocket`) are registered in `BUILTIN_COMPONENT_TEMPLATE_PATHS` in `template_registry.py`. Adding a new template means dropping a `.yaml` under `dsl_templates/` and registering it there.
- **DSL changes that touch examples**: keep `examples/dsl/*.metal.yaml` and the matching notebooks/`run_*_demo.py` scripts in sync — they double as documentation and as smoke tests.
