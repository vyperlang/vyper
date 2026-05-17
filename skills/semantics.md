# Semantics & Frontend

Type checking, validation, and semantic analysis of Vyper AST.

Primary reference: [vyper/semantics/README.md](../vyper/semantics/README.md) — full control flow, design, examples.

## Pipeline

```
Source → pre_parser → Python AST → Vyper AST → semantic analysis → annotated AST
```

### AST Phase (`vyper/ast/`)

See [vyper/ast/README.md](../vyper/ast/README.md).

- `pre_parser.py`: Vyper source → parseable Python (substitutes `struct`/`interface` → `class`, etc.)
- `grammar.lark`: Lark grammar definition
- `nodes.py`: Vyper AST node classes (use `__slots__`)
- `parse.py` / `utils.py`: `parse_to_ast()` — main entry

### Semantic Analysis Phase (`vyper/semantics/`)

Entry: `vyper.semantics.analyze_module()`

Four steps:
1. **Pre-typecheck** (`analysis/pre_typecheck.py`): fold constant expressions
2. **Namespace init** (`namespace.py`): populate builtins, types, env vars
3. **Module validation** (`analysis/module.py`): storage vars, user types, imports, function sigs
4. **Local validation** (`analysis/local.py`): per-function type checking and annotation

## Type System (`vyper/semantics/types/`)

Type classes live in `vyper/semantics/types/`. Convention: classes end in `T` (e.g. `IntegerT`, `ModuleT`).
Base classes in `bases.py`. Browse the directory for the full set — file names map to type categories
(primitives, bytestrings, subscriptable, user-defined, function, module).

Type checking is bottom-up: evaluate expression types → compare sides → validate operation.

## Namespace

`Namespace` (`namespace.py`) is a dict subclass with scoping via context manager:

```python
with namespace.enter_scope():
    namespace["x"] = some_type
# x no longer exists here
```

Scopes: builtin → module → local → (for/if blocks).

## Analysis

Analysis and validation logic lives in `vyper/semantics/analysis/`. Key files:
- `module.py` — module-level validation (storage, types, imports)
- `local.py` — `FunctionNodeVisitor`, per-function validation
- `annotation.py` — type annotation of expressions

Browse the directory for the full set. Also see `data_locations.py` and `environment.py` at the `semantics/` level.
