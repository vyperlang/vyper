---
name: vyper-compiler
description: Vyper smart contract compiler internals. Use when working on the Vyper compiler codebase — compilation pipeline, Venom IR, semantic analysis, code generation, testing, or contributing. Triggers on vyper compiler development, Venom passes, AST/semantics changes, codegen work, or test writing.
---

# Vyper Compiler

Pythonic smart contract language targeting the EVM. v0.4.x, Python 3.11+.

## Quick Commands

```bash
uv sync --extra dev              # install deps (per-worktree .venv, recommended)
uv run vyper contract.vy                # compile a contract
uv run vyper -f ir_runtime contract.vy  # inspect Venom IR
uv run vyper -f asm contract.vy         # inspect assembly
uv run ./quicktest.sh -m "not fuzzing"  # run tests (-nauto by default via setup.cfg)
uv run make lint                        # enforces code style (same as CI)
```

Prefix all commands with `uv run` — it activates the local `.venv` per invocation, which is necessary in non-interactive shells. Each worktree gets its own `.venv`, so no cross-contamination.

Alternative: `pip install ".[dev]"` + `PYTHONPATH=.` prefix on every command. **Never `pip install -e .`** — it creates an egg-link in site-packages that permanently points the venv at one worktree, breaking all others.

## Compilation Pipeline

```
Source (.vy)
  │
  ├─ vyper/ast/            → Parse to AST (pre_parser → Python AST → Vyper AST)
  ├─ vyper/semantics/      → Type check, validate, annotate AST
  ├─ vyper/codegen/        → AST → s-expr IR (default production pipeline)
  ├─ vyper/ir/             → s-expr IR → assembly → bytecode
  └─ vyper/evm/            → Assembly → bytecode
```

Experimental Venom path (`--experimental-codegen`):
```
  ├─ vyper/codegen_venom/  → AST → Venom SSA IR
  └─ vyper/venom/          → Venom IR optimization passes → assembly
```

Orchestrated by `vyper/compiler/phases.py` (`CompilerData`). Each phase is lazy.

## Directory Map

| Directory | Purpose |
|-----------|---------|
| `vyper/ast/` | Parsing, AST nodes, pre-parser. See [AST README](../vyper/ast/README.md) |
| `vyper/semantics/` | Type system, analysis, validation. See [Semantics README](../vyper/semantics/README.md) |
| `vyper/codegen/` | AST → s-expr IR (default production pipeline) |
| `vyper/ir/` | s-expr IR → assembly → bytecode. See [IR README](../vyper/ir/README.md) |
| `vyper/codegen_venom/` | AST → Venom IR (experimental, `--experimental-codegen`) |
| `vyper/venom/` | Venom SSA IR: passes, analysis, assembly emission. See [Venom README](../vyper/venom/README.md) |
| `vyper/compiler/` | Pipeline orchestration, settings, output formats. See [Compiler README](../vyper/compiler/README.md) |
| `vyper/builtins/` | Built-in functions and interfaces |
| `vyper/evm/` | EVM opcodes, assembler |
| `vyper/cli/` | CLI entry points (`vyper`, `vyper-ir`, `venom`) |
| `tests/unit/` | Unit tests (ast, semantics, compiler, venom) |
| `tests/functional/` | Functional tests (builtins, codegen, grammar, syntax, venom) |

## Topic Deep-Dives

- **[Venom IR](venom.md)** — SSA IR design, passes, optimization, working with Venom code
- **[Semantics & Frontend](semantics.md)** — Type system, analysis phases, namespace, validation
- **[Code Generation](codegen.md)** — Legacy IR, Venom codegen, the two pipelines
- **[Testing](testing.md)** — Test structure, fixtures, running tests, writing new tests
- **[Contributing](contributing.md)** — Commit message standards, PR workflow, code style summary

## Code Style

Enforced by `make lint` (also what CI runs). Includes `black`, `flake8`, `isort`, `mypy`.

- Line length: 100
- No inline imports; standard library → third-party → local
- snake_case throughout; type classes end in `T` (e.g. `IntegerT`, `ModuleT`)

## Key Entry Points

| What | Where |
|------|-------|
| Main compile function | `vyper.compiler.compile_code()` |
| Pipeline phases | `vyper.compiler.phases.CompilerData` |
| AST parsing | `vyper.ast.parse.parse_to_ast()` |
| Semantic analysis | `vyper.semantics.analyze_module()` |
| Legacy codegen | `vyper.codegen.module` |
| AST → Venom IR | `vyper.codegen_venom.module` |
| Venom → assembly | `vyper.venom.generate_assembly_experimental()` |
| CLI entry | `vyper.cli.vyper_compile` |
