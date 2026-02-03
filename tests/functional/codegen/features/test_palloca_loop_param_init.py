"""
Regression test for palloca param initialization being incorrectly repeated in loops.

When a stack-passed parameter is copied into palloca inside a loop body, the
initializer mstore was being left in the loop after FloatAllocas moved the
palloca to the entry block. This re-initialized the parameter each iteration,
breaking loop-carried dependencies and suppressing expected reverts.
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


def test_mod_by_zero_in_loop_reverts(get_contract, tx_failed, no_inline_settings):
    code = """
@internal
def _helper(x: uint256) -> uint256:
    for i: uint256 in range(2):
        x %= x  # iter1: 1%1=0, iter2: 0%0 should revert
    return 0

@external
def foo() -> uint256:
    self._helper(1)
    return 42
    """

    c = get_contract(code, compiler_settings=no_inline_settings)
    with tx_failed():
        c.foo()
