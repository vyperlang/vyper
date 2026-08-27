"""
Tests for the OverflowEliminationPass.

This pass eliminates overflow checks when VRA can prove the pattern is safe,
specifically when both operands are range-bounded such that no wrap can occur.
"""

from tests.venom_utils import PrePostChecker
from vyper.venom.passes.overflow_elimination import OverflowEliminationPass
from vyper.venom.passes.remove_unused_variables import RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker([OverflowEliminationPass, RemoveUnusedVariablesPass])


def test_eliminate_add_overflow_bounded_operands():
    """
    Eliminate add overflow check when both operands are non-negative and bounded.
    """
    pre = """
    main:
        %x_in = source
        %y_in = source
        %x = and %x_in, 255
        %y = and %y_in, 255
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x_in = source
        %y_in = source
        %x = and %x_in, 255
        %y = and %y_in, 255
        %res = add %x, %y
        sink %res
    """

    _check_pre_post(pre, post)


def test_eliminate_sub_underflow_bounded_operands():
    """
    Eliminate sub underflow check when min(x) >= max(y).
    """
    pre = """
    main:
        %x_in = source
        %y_in = source
        %x_base = and %x_in, 100
        %x = add %x_base, 100
        %y = and %y_in, 50
        %res = sub %x, %y
        %cmp = gt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x_in = source
        %y_in = source
        %x_base = and %x_in, 100
        %x = add %x_base, 100
        %y = and %y_in, 50
        %res = sub %x, %y
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_add_overflow_constant_y():
    """
    Do NOT eliminate when only y is known non-negative and x is unbounded.
    """
    pre = """
    main:
        %x = source
        %res = add %x, 100
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %res = add %x, 100
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_sub_underflow_constant_y():
    """
    Do NOT eliminate when only y is known non-negative and x is unbounded.
    """
    pre = """
    main:
        %x = source
        %res = sub %x, 50
        %cmp = gt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %res = sub %x, 50
        %cmp = gt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_add_overflow_masked_y():
    """
    Do NOT eliminate when only y is range-bounded.
    """
    pre = """
    main:
        %x = source
        %input = source
        %y = and %input, 255
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %input = source
        %y = and %input, 255
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_sub_underflow_masked_y():
    """
    Do NOT eliminate when only y is range-bounded.
    """
    pre = """
    main:
        %x = source
        %input = source
        %y = and %input, 255
        %res = sub %x, %y
        %cmp = gt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %input = source
        %y = and %input, 255
        %res = sub %x, %y
        %cmp = gt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_unknown_y():
    """
    Do NOT eliminate when y has unknown range.
    """
    pre = """
    main:
        %x = source
        %y = source
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %y = source
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_add_with_mod_y():
    """
    Do NOT eliminate when only y is non-negative via modulo.
    """
    pre = """
    main:
        %x = source
        %input = source
        %y = mod %input, 1000
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x = source
        %input = source
        %y = mod %input, 1000
        %res = add %x, %y
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_eliminate_add_overflow_swapped_operand_order():
    """
    Eliminate add overflow check when operands are swapped (add %y, %x).
    The check compares result to %x, but %x is the second operand in add.
    """
    pre = """
    main:
        %x_in = source
        %y_in = source
        %x = and %x_in, 255
        %y = and %y_in, 255
        %res = add %y, %x
        %cmp = lt %res, %x
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x_in = source
        %y_in = source
        %x = and %x_in, 255
        %y = and %y_in, 255
        %res = add %y, %x
        sink %res
    """

    _check_pre_post(pre, post)


def test_no_eliminate_sub_underflow_wrong_operand_compared():
    """
    Do NOT eliminate sub underflow check when comparing to y instead of x.
    The correct pattern is: res = sub %x, %y; cmp = gt %res, %x
    Comparing to %y is wrong and should NOT be eliminated.
    """
    pre = """
    main:
        %x_in = source
        %y_in = source
        %x_base = and %x_in, 100
        %x = add %x_base, 100
        %y = and %y_in, 50
        %res = sub %x, %y
        %cmp = gt %res, %y
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %x_in = source
        %y_in = source
        %x_base = and %x_in, 100
        %x = add %x_base, 100
        %y = and %y_in, 50
        %res = sub %x, %y
        %cmp = gt %res, %y
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    _check_pre_post(pre, post)


def test_eliminate_add_overflow_both_constants():
    """
    Eliminate add overflow check when both operands are constants.
    Constants have known ranges, so the pass should prove no overflow.
    """
    pre = """
    main:
        %res = add 100, 200
        %cmp = lt %res, 100
        %ok = iszero %cmp
        assert %ok
        sink %res
    """

    post = """
    main:
        %res = add 100, 200
        sink %res
    """

    _check_pre_post(pre, post)
