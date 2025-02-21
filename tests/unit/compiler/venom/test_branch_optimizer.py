from tests.hevm import hevm_check_venom
from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import BranchOptimizationPass


def _check_pre_post(pre: str, post: str, hevm: bool = True):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        BranchOptimizationPass(ac, fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))

    if not hevm:
        return

    hevm_check_venom(pre, post)


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
