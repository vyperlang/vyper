# Testing

## Running Tests

```bash
./quicktest.sh -m "not fuzzing"          # standard test run (-nauto by default via setup.cfg)
./quicktest.sh tests/unit/               # unit tests only
./quicktest.sh tests/functional/         # functional tests only
./quicktest.sh tests/unit/compiler/venom/ # venom unit tests
./quicktest.sh --hevm -m hevm            # hevm-based tests (needs hevm in PATH)
```

`quicktest.sh` wraps pytest with `-q -s --instafail -x` (bail on first failure).

CI runs the fuzzing matrix on both legacy and Venom codegen, using 120 duration-based
shards per backend. To run fuzzing locally, use `pytest -m fuzzing`; add
`--experimental-codegen` for Venom.

Conversion fuzzing distinguishes compile-time rejection from runtime clamping. Literal
conversions may be rejected by constant folding or Venom's SCCP. The constant-local
runtime case sets `disable_static_exceptions=True` to retain the failing assertion in
bytecode; the calldata-input case uses the normal compiler settings.

## Test Organization

```
tests/
├── unit/           # isolated component tests
│   ├── ast/
│   ├── semantics/
│   ├── compiler/
│   │   └── venom/  # venom pass & analysis tests
│   ├── cli/
│   └── ...
├── functional/     # end-to-end compilation & execution
│   ├── builtins/
│   ├── codegen/
│   ├── grammar/
│   ├── syntax/
│   └── venom/
├── conftest.py     # shared fixtures
├── evm_backends/   # EVM execution backends for tests
└── venom_utils.py  # helpers for venom tests
```

## Key Fixtures & Helpers

- `tests/conftest.py` — main fixtures (compiler invocation, EVM backends)
- `tests/evm_backends/` — pluggable EVM execution (pyevm, pyrevm)
- `tests/venom_utils.py` — helpers for constructing Venom IR in tests

## Writing Tests

- Functional tests typically compile a Vyper snippet and execute it against an EVM backend
- Venom unit tests construct IR programmatically, run passes, and assert on the result
- Use `pytest.mark.fuzzing` for slow/fuzz tests (skipped in quick runs)
- Use `pytest.mark.hevm` for hevm-specific tests
