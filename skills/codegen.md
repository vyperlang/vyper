# Code Generation

## Experimental Pipeline: Direct-to-Venom

AST → `vyper/codegen_venom/` → Venom IR → optimization passes → assembly → bytecode.

### `vyper/codegen_venom/`

Translates annotated Vyper AST directly to Venom SSA IR.

- `module.py` — entry point, module-level codegen
- `expr.py` — expression translation
- `stmt.py` — statement translation
- `arithmetic.py` — numeric operations
- `builtins/` — built-in function codegen
- `abi/` — ABI encoding/decoding
- `context.py` — codegen context (variable tracking, etc.)

### Venom → Assembly

After Venom IR is constructed, `vyper/venom/` runs optimization passes then
`venom/venom_to_assembly.py` emits EVM assembly. The assembler in `vyper/evm/assembler/`
produces final bytecode.

## Default Production Pipeline: Legacy IR

AST → `vyper/codegen/` → s-expression IR (`IRnode`) → `vyper/ir/compile_ir.py` → assembly → bytecode.

This is the current default. See [vyper/ir/README.md](../vyper/ir/README.md) for IR grammar and structure.

Key difference: legacy IR is tree-shaped s-expressions, Venom is SSA basic blocks.
