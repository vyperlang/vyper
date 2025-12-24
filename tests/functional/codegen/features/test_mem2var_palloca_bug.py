"""
Regression test for mem2var palloca miscompile bug.

The bug occurred when:
1. An internal function has a memory-passed parameter (>32 bytes)
2. The palloca is only used for mload/mstore at offset 0 (no pointer arithmetic)
3. mem2var incorrectly used the SIZE as the mload address instead of the actual address

Tests disable function inlining to ensure the palloca code path is exercised.
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
def test_mem2var_palloca_struct_first_field(get_contract, no_inline_settings):
    """
    A 64-byte struct is passed via memory. Accessing only the first field
    (offset 0) means no pointer arithmetic, which triggered the bug.
    """
    code = """
struct Pair:
    first: uint256
    second: uint256

@internal
def _get_first(p: Pair) -> uint256:
    return p.first

@external
def test_val() -> uint256:
    x: Pair = Pair(first=12345, second=99999)
    return self._get_first(x)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == 12345


@pytest.mark.hevm
def test_mem2var_palloca_array_first_element(get_contract, no_inline_settings):
    """
    A 64-byte array (uint256[2]) passed via memory. Accessing only arr[0]
    (offset 0) means no pointer arithmetic, which triggered the bug.
    """
    code = """
@internal
def _get_first(arr: uint256[2]) -> uint256:
    return arr[0]

@external
def test_val() -> uint256:
    a: uint256[2] = [12345, 67890]
    return self._get_first(a)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == 12345


@pytest.mark.hevm
def test_mem2var_palloca_bytes32_array(get_contract, no_inline_settings):
    """
    Test with bytes32[2] array (64 bytes, memory-passed).
    """
    code = """
@internal
def _get_first(arr: bytes32[2]) -> bytes32:
    return arr[0]

@external
def test_val() -> bytes32:
    a: bytes32[2] = [
        0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,
        0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    ]
    return self._get_first(a)
    """
    c = get_contract(code, compiler_settings=no_inline_settings)
    assert c.test_val() == bytes.fromhex("aa" * 32)
