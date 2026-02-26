# Vyper Compiler — Agent Guide

Pythonic smart contract language targeting the EVM. v0.4.x, Python 3.11+.

## Quick Commands

```bash
pip install -e ".[dev]"                  # one-time: install dev deps
PYTHONPATH=. vyper contract.vy           # compile using local source
PYTHONPATH=. vyper -f ir_runtime contract.vy # inspect Venom IR
PYTHONPATH=. vyper -f asm contract.vy    # inspect assembly
./quicktest.sh -m "not fuzzing"          # run tests (-nauto by default via setup.cfg)
make lint                                # enforces code style (same as CI)
```

## Architecture, Code Style, Entry Points

See [skills/SKILL.md](skills/SKILL.md) for compilation pipeline, directory map, code style, and key entry points.

## Topic Deep-Dives

- **[Venom IR](skills/venom.md)** — SSA IR design, passes, optimization, working with Venom code
- **[Semantics & Frontend](skills/semantics.md)** — Type system, analysis phases, namespace, validation
- **[Code Generation](skills/codegen.md)** — Legacy IR, Venom codegen, the two pipelines
- **[Testing](skills/testing.md)** — Test structure, fixtures, running tests, writing new tests
- **[Contributing](skills/contributing.md)** — Commit message standards, PR workflow, code style summary
