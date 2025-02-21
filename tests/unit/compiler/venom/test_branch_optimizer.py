import pytest

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import BranchOptimizationPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(BranchOptimizationPass)


def test_simple_jump_case():
    pre = """
    main:
        %p1 = param
        %p2 = param

        %op1 = %p1
        %op2 = 64
        %op3 = add %op1, %op2

        ; this condition can be inversed
        %cond = iszero %op3
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
        %p1 = param
        %p2 = param

        %op1 = %p1
        %op2 = 64
        %op3 = add %op1, %op2

        %cond = iszero %op3
        jnz %op3, @br2, @br1
    br1:
        %res1 = add %op3, %op1
        sink %res1
    br2:
        %res2 = add %op3, %op2
        sink %res2
    """
    _check_pre_post(pre, post)
