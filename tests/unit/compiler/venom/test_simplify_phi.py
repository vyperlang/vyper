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
        %y:1 = %x
        jmp @exit
    else:
        %y:2 = %x
        jmp @exit
    exit:
        %result = phi @then, %y:1, @else, %y:2
        sink %result
    """

    post = """
    _global:
        %x = param
        jnz 1, @then, @else
    then:
        %y:1 = %x
        jmp @exit
    else:
        %y:2 = %x
        jmp @exit
    exit:
        %result = %x
        sink %result
    """

    _check_pre_post(pre, post)


def test_no_simplify_different_phi_operands():
    """
    Test that phi nodes with different operands are not simplified.
    """
    pre = """
    _global:
        %x = param
        %y = param
        jnz %x, @then, @else
    then:
        %z:1 = %x
        jmp @exit
    else:
        %z:2 = %y
        jmp @exit
    exit:
        %result = phi @then, %x, @else, %y
        sink %result
    """

    _check_no_change(pre)


def test_simplify_with_closest_dominating_var():
    """
    Test that phi nodes are simplified to the closest dominating var
    """
    pre = """
    main:
        %x = param
        %y = param
        jmp @next
    next:
        %z = %x
        jnz %y, @then, @else
    then:
        %z:1 = %z
        jmp @exit
    else:
        %z:2 = %z
        jmp @exit
    exit:
        %result = phi @then, %z:1, @else, %z:2
        sink %result
    """
    post = """
    main:
        %x = param
        %y = param
        jmp @next
    next:
        %z = %x
        jnz %y, @then, @else
    then:
        %z:1 = %z
        jmp @exit
    else:
        %z:2 = %z
        jmp @exit
    exit:
        %result = %z
        sink %result
    """
    _check_pre_post(pre, post)
