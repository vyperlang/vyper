# Venom IR

SSA-based intermediate representation for Vyper. Inspired by LLVM IR, adapted for stack-based EVM.

Primary reference: [vyper/venom/README.md](../vyper/venom/README.md) — full instruction set, grammar, examples.

## Structure

```
IRContext → IRFunction(s) → IRBasicBlock(s) → IRInstruction(s)
```

- Variables: `%`-prefixed, immutable after assignment (SSA)
- Basic blocks: non-branching, terminated by `jmp`/`jnz`/`djmp`/`ret`/`return`/`stop`/`exit`
- Normalized form: no block has both multiple predecessors AND multiple successors

## Key Files

Core data structures in `vyper/venom/`:
- `context.py` — `IRContext`, top-level container
- `function.py` — `IRFunction`
- `basicblock.py` — `IRBasicBlock`, `IRInstruction`, `IROperand`
- `builder.py` — helper for programmatic IR construction
- `venom_to_assembly.py` — final pass: Venom → EVM assembly
- `parser.py` — text format parser (for testing)

Passes and analysis live in `venom/passes/` and `venom/analysis/` respectively.

## Pass Architecture

Passes inherit from base classes in `venom/passes/base_pass.py`. Three categories:
- **Analysis** — `venom/analysis/` (CFG, DFG, liveness, dominators, etc.)
- **Transformation** — normalization, SSA construction, phi elimination
- **Optimization** — DCE, SCCP, CSE, load elimination, mem2var, inlining, etc.

Pass ordering matters — e.g. assembly emission requires normalization, which requires CFG.

Browse `venom/passes/` and `venom/analysis/` for the full set. File names are self-descriptive.

## Inspecting Venom Output

```bash
vyper -f ir_runtime contract.vy        # Venom IR (runtime)
vyper -f ir contract.vy                # Venom IR (deploy)
vyper -f cfg_runtime contract.vy       # CFG as dot graph
vyper -f asm contract.vy               # final assembly
```

Enable Venom: `--experimental-codegen` flag or `#pragma experimental-codegen` in source.

## Entry Path

AST → `vyper/codegen_venom/` → Venom IR (direct translation, no legacy IR involved).
Entry point: `vyper/codegen_venom/module.py`.
