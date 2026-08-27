import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AssertCombinerPass, RemoveUnusedVariablesPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([AssertCombinerPass, RemoveUnusedVariablesPass])


def test_combine_adjacent_asserts():
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """

    post = """
    main:
        %1 = source
        %3 = source
        %5 = or %3, %1
        %6 = iszero %5
        assert %6
        sink %3
    """
    _check_pre_post(pre, post)


def test_skip_non_boolean_asserts():
    pre = """
    main:
        %1 = 2
        assert %1
        %2 = source
        %3 = iszero %2
        assert %3
        sink %2
    """

    post = """
    main:
        %1 = 2
        assert %1
        %2 = source
        %3 = iszero %2
        assert %3
        sink %2
    """
    _check_pre_post(pre, post)


def test_combine_three_asserts():
    """Three consecutive asserts should all merge into one."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %3 = source
        %4 = iszero %3
        assert %4
        %5 = source
        %6 = iszero %5
        assert %6
        sink %5
    """

    post = """
    main:
        %1 = source
        %3 = source
        %7 = or %3, %1
        %5 = source
        %9 = or %5, %7
        %10 = iszero %9
        assert %10
        sink %5
    """
    _check_pre_post(pre, post)


def test_side_effect_breaks_chain():
    """Side-effecting instruction between asserts should break the chain."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        mstore 0, 42
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """

    post = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        mstore 0, 42
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """
    _check_pre_post(pre, post)


def test_pure_instruction_between_asserts():
    """Pure instructions between asserts should NOT break the chain."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = add 1, 2
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3, %x
    """

    post = """
    main:
        %1 = source
        %x = add 1, 2
        %3 = source
        %5 = or %3, %1
        %6 = iszero %5
        assert %6
        sink %3, %x
    """
    _check_pre_post(pre, post)


def test_assign_chain_before_iszero():
    """Assign chain before iszero should be followed correctly."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        %2a = %2
        %2b = %2a
        assert %2b
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """

    post = """
    main:
        %1 = source
        %3 = source
        %5 = or %3, %1
        %6 = iszero %5
        assert %6
        sink %3
    """
    _check_pre_post(pre, post)


def test_same_predicate_removes_duplicate():
    """Two asserts on the same predicate should collapse to one."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %3 = iszero %1
        assert %3
        sink %1
    """

    post = """
    main:
        %1 = source
        %3 = iszero %1
        assert %3
        sink %1
    """
    _check_pre_post(pre, post)


def test_non_iszero_between_iszero_asserts():
    """Non-iszero assert between two iszero asserts should reset the chain."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = 1
        assert %x
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """

    post = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = 1
        assert %x
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3
    """
    _check_pre_post(pre, post)


def test_single_assert_unchanged():
    """A single iszero assert should remain unchanged."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        sink %1
    """

    post = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        sink %1
    """
    _check_pre_post(pre, post)


def test_sload_breaks_chain():
    """Storage read between asserts should break the chain (has read effects)."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = sload 0
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3, %x
    """

    post = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = sload 0
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3, %x
    """
    _check_pre_post(pre, post)


def test_iszero_of_literal():
    """iszero of a literal should be combinable."""
    pre = """
    main:
        %1 = iszero 0
        assert %1
        %2 = source
        %3 = iszero %2
        assert %3
        sink %2
    """

    post = """
    main:
        %2 = source
        %4 = or %2, 0
        %5 = iszero %4
        assert %5
        sink %2
    """
    _check_pre_post(pre, post)


def test_mload_breaks_chain():
    """Memory read between asserts should break the chain (has read effects)."""
    pre = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = mload 0
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3, %x
    """

    post = """
    main:
        %1 = source
        %2 = iszero %1
        assert %2
        %x = mload 0
        %3 = source
        %4 = iszero %3
        assert %4
        sink %3, %x
    """
    _check_pre_post(pre, post)
