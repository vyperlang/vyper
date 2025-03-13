import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import SimplifyPhiPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([SimplifyPhiPass])


def _check_no_change(pre):
    """Helper that verifies a pass doesn't change the input."""
    _check_pre_post(pre, pre, hevm=False)


def test_simplify_identical_phi_operands():
    """
    Test that phi nodes with identical operands are simplified to direct assignments.
    """
    pre = """
    _global:
        %x = param
        jnz 1, @then, @else
    then:
        %y = %x
        jmp @exit
    else:
        %y = %x
        jmp @exit
    exit:
        %result = phi @then, %y, @else, %y
        sink %result
    """

    post = """
    _global:
        %x = param
        jnz 1, @then, @else
    then:
        %y = %x
        jmp @exit
    else:
        %y = %x
        jmp @exit
    exit:
        %result = %y
        sink %result
    """

    _check_pre_post(pre, post)


def test_simplify_identical_phi_with_literals():
    """
    Test that phi nodes with identical literal operands are simplified.
    """
    pre = """
    _global:
        %condition = param
        jnz %condition, @then, @else
    then:
        jmp @exit
    else:
        jmp @exit
    exit:
        %result = phi @then, 42, @else, 42
        sink %result
    """

    post = """
    _global:
        %condition = param
        jnz %condition, @then, @else
    then:
        jmp @exit
    else:
        jmp @exit
    exit:
        %result = 42
        sink %result
    """

    _check_pre_post(pre, post)


def test_dont_simplify_different_phi_operands():
    """
    Test that phi nodes with different operands are not simplified.
    """
    pre = """
    _global:
        %x = param
        %y = param
        jnz 1, @then, @else
    then:
        %z = %x
        jmp @exit
    else:
        %z = %y
        jmp @exit
    exit:
        %result = phi @then, %x, @else, %y
        sink %result
    """

    _check_no_change(pre)
