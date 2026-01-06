# revert_on_failure for external calls

This document describes the behavior and implementation of `revert_on_failure`
for external calls (extcall/staticcall), including return typing, codegen
details, and test coverage.

## Overview

`revert_on_failure` allows external calls to return a success flag instead of
reverting on call failure. When `revert_on_failure=False`, the call returns a tuple
`(success, value)` where:

- `success` is a `bool` indicating whether the external call succeeded.
- `value` is the original return type of the external function. On failure,
  `value` is the default (zero) value for its type.

For external functions that return nothing, the return type is just `bool`.

This behavior was previously only available for `raw_call`. It is now supported
for typed external calls via `extcall` and `staticcall`.

Important: `revert_on_failure` only applies to the EVM call result (i.e. the
`CALL`/`STATICCALL` success flag). ABI decoding still enforces return data size
and type checks, and the extcodesize check for no-return calls still applies.
Those conditions can still revert even when `revert_on_failure=False`.

## Enabled behaviors

With this change, all external calls can opt into non-reverting behavior:

- `extcall Target(addr).fn(..., revert_on_failure=False)`
- `staticcall Target(addr).fn(..., revert_on_failure=False)`

Return typing:

- For functions with a return value `T`, the call returns `(bool, T)` when
  `revert_on_failure=False`.
- For functions with no return value, the call returns `bool`.

This matches the existing `raw_call` behavior and keeps return values ABI-safe.

## Implementation details

### Semantics: return typing

Return types for external calls are adjusted in
`vyper/semantics/types/function.py`:

- When `revert_on_failure=False`, the return type becomes `bool` (no-return
  functions) or `(bool, return_type)` for functions with a return value.

### Codegen: external calls

External call codegen lives in `vyper/codegen/external_call.py`.

Key behaviors added/updated:

- The call success flag is normalized to a real boolean (0 or 1) before it is
  stored in the tuple or used for control flow. This prevents non-boolean
  values from leaking into the ABI-encoded return tuple.
- On call failure, the return buffer for the "value" portion is zeroed to
  ensure default return values for all types (including dynamic types) and
  avoid reading/returning stale or revert data.
- Return data is only decoded when the call succeeds.

These changes ensure that tuple returns are ABI-decodable and safe in all
failure cases.

### Codegen: return fast-path safety

The external return fast-path in `vyper/codegen/return_.py` previously skipped
ABI encoding when the return value was already in ABI-compatible memory. This
optimization now excludes expressions that contain risky calls.

Rationale:

- Directly returning the result of a risky call (e.g. `return extcall ...`)
  can produce a memory pointer that is not safe to use as a return buffer
  without re-encoding.
- Disabling the skip-encode path for risky calls ensures return offsets and
  lengths are well-formed, avoiding invalid memory expansion or out-of-gas
  errors when returning from external functions.

## Tests

Targeted tests were added and updated in
`tests/functional/codegen/calling_convention/test_external_contract_calls.py`:

- `test_external_contract_call_revert_on_failure_noreturn_direct_return`
  - Direct `return extcall ...` for no-return functions; verifies `bool`.
- `test_external_contract_call_revert_on_failure_direct_return`
  - Direct `return extcall ...` for value-returning functions; verifies
    `(bool, value)` and zero defaults on failure.
- `test_external_contract_call_revert_on_failure_staticcall`
  - `staticcall` with `revert_on_failure=False`, using assignment to verify
    `(bool, value)` and zero defaults on failure.

Existing tests for revert-on-failure behavior with structs, arrays, and strings
continue to pass, covering dynamic types and ABI decoding correctness.

## Examples

### No-return external call

```vyper
interface Target:
    def fail(should_raise: bool): nonpayable

@external
def call_target_fail(target: address, should_raise: bool) -> bool:
    return extcall Target(target).fail(should_raise, revert_on_failure=False)
```

### Value-returning external call

```vyper
interface Target:
    def value(should_raise: bool) -> uint256: nonpayable

@external
def call_target_value(target: address, should_raise: bool) -> (bool, uint256):
    success, result = extcall Target(target).value(should_raise, revert_on_failure=False)
    return success, result
```

### Multi-return external call

```vyper
interface Target:
    def values(should_raise: bool) -> (uint256, bytes32): nonpayable

@external
def call_target_values(
    target: address,
    should_raise: bool
) -> (bool, (uint256, bytes32)):
    return extcall Target(target).values(should_raise, revert_on_failure=False)
```

### Staticcall with revert_on_failure

```vyper
interface Target:
    def value(should_raise: bool) -> uint256: view

@external
def call_target_value(target: address, should_raise: bool) -> (bool, uint256):
    return staticcall Target(target).value(should_raise, revert_on_failure=False)
```

## Test runs

Commands used during validation:

```
uv run pytest tests/functional/codegen/calling_convention/test_external_contract_calls.py -q
uv run ./quicktest.sh -m "not fuzzing"
```

These runs validated both the focused external call behavior and the broader
test suite without fuzzing tests.

## Documentation updates

The interface call kwargs table in `docs/interfaces.rst` now includes
`revert_on_failure` and its tuple-return behavior when set to `False`.
