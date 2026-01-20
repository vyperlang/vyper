"""
Regression tests for mem2var/palloca/calloca handling.

Tests memory-passed parameter handling when DSE eliminates unused
stores to palloca memory. The corresponding calloca and mcopy in
the caller should also be eliminated.
"""
import copy

import pytest

from vyper.compiler.settings import VenomOptimizationFlags


@pytest.fixture
def no_inline_settings(compiler_settings):
    """Create settings with function inlining disabled (venom only)."""
    settings = copy.copy(compiler_settings)
    if settings.experimental_codegen:
        settings.venom_flags = VenomOptimizationFlags(disable_inlining=True)
    return settings


@pytest.mark.hevm
def test_mem2var_mstore_single_field_struct(get_contract, no_inline_settings):
    """
    A struct with a single uint256 field (32 bytes) should trigger the bug
    if it's memory-passed with size == 32.

    The function writes to the struct field, then reads it back.
    If mstore is incorrectly converted to assign, the write might be lost.
    """
    code = """
struct Single:
    value: uint256

@internal
def _write_and_read(s: Single) -> uint256:
    s.value = 42
    return s.value

@external
def test_val() -> uint256:
    x: Single = Single(value=0)
    return self._write_and_read(x)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == 42


@pytest.mark.hevm
def test_mem2var_calloca_tracking_bug(get_contract, no_inline_settings):
    """
    Test that unused palloca parameters are handled correctly.

    When DSE eliminates stores to palloca (because the callee doesn't read
    the parameter), the corresponding calloca in the caller should also be
    eliminated along with the mcopy that populates it.
    """
    code = """
struct Pair:
    first: uint256
    second: uint256

@internal
def _modify_first(p: Pair):
    p.first = 999

@external
def test_val() -> uint256:
    x: Pair = Pair(first=0, second=0)
    self._modify_first(x)
    return x.first
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == 0  # by-value semantics: callee modification doesn't affect caller


@pytest.mark.hevm
def test_mem2var_mstore_then_mload_same_location(get_contract, no_inline_settings):
    """
    Test writing then reading from the same palloca location.

    The mstore should update memory, and the subsequent mload should see it.
    If mem2var creates two definitions of the same variable, behavior is undefined.
    """
    code = """
struct Single:
    value: uint256

@internal
def _overwrite(s: Single) -> uint256:
    original: uint256 = s.value
    s.value = 123
    new_val: uint256 = s.value
    return original * 1000 + new_val

@external
def test_val() -> uint256:
    x: Single = Single(value=7)
    return self._overwrite(x)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    # Should return 7*1000 + 123 = 7123
    assert c.test_val() == 7123


@pytest.mark.hevm
def test_mem2var_mstore_bytes32_single(get_contract, no_inline_settings):
    """
    Test with a single bytes32 value in a struct (exactly 32 bytes).
    This is a likely candidate for size == 32 memory-passed param.
    """
    code = """
struct HashContainer:
    hash: bytes32

@internal
def _swap_hash(h: HashContainer) -> bytes32:
    old: bytes32 = h.hash
    h.hash = 0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    return old

@external
def test_val() -> bytes32:
    x: HashContainer = HashContainer(
        hash=0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    )
    return self._swap_hash(x)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == bytes.fromhex("bb" * 32)
