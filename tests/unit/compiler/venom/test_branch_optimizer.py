import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import BranchOptimizationPass, RemoveUnusedVariablesPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker([BranchOptimizationPass, RemoveUnusedVariablesPass])


def test_simple_jump_case():
    """
    Test that it removes the case when
    it can remove iszero and switch branches
    """

    pre = """
    main:
        %p1 = source

        %op1 = %p1
        %op2 = 64
        %op3 = add %op1, %op2

        %cond = iszero %op3
        ; this condition will be inverted
        jnz %cond, @br1, @br2
    br1:
        %res1 = add %op3, %op1
        sink %res1
    br2:
        %res2 = add %op3, %op2
        sink %res2
    """

    post = """
    main:
        %p1 = source

        %op1 = %p1
        %op2 = 64
        %op3 = add %op1, %op2

        ; swapped branches
        jnz %op3, @br2, @br1
    br1:
        %res1 = add %op3, %op1
        sink %res1
    br2:
        %res2 = add %op3, %op2
        sink %res2
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("cond", [0, 1])
def test_deterministic_literal_condition(cond):
    """
    Test that the pass does not crash when the jnz condition is a
    literal, i.e. the branch is deterministic at compile time.
    The pass should leave the branch untouched (folding it into a
    jmp is sccp/simplify_cfg's job).
    """
    pre = f"""
    main:
        %p1 = source
        %op1 = add %p1, 1
        jnz {cond}, @br1, @br2
    br1:
        sink %op1
    br2:
        sink 2
    """
    _check_pre_post(pre, pre)

