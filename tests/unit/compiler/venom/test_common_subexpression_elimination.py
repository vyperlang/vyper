from tests.venom_utils import assert_ctx_eq, parse_from_basic_block, parse_venom
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes.common_subexpression_elimination import CSE


def _check_pre_post(pre: str, post: str):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        CSE(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_from_basic_block(post))


def _check_pre_post_fn(pre: str, post: str):
    ctx = parse_venom(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        CSE(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_venom(post))


def _check_no_change(pre: str):
    _check_pre_post(pre, pre)


def _check_no_change_fn(pre: str):
    _check_pre_post_fn(pre, pre)


def test_common_subexpression_elimination():
    pre = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = add %1, 10
        %mul2 = mul %sum2, 10
        return %mul1, %mul2
    """

    post = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = %sum1
        %mul2 = %mul1
        return %mul1, %mul2
    """

    _check_pre_post(pre, post)


def test_common_subexpression_elimination_commutative():
    pre = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = add 10, %1
        %mul2 = mul 10, %sum2
        return %mul1, %mul2
    """

    post = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = %sum1
        %mul2 = %mul1
        return %mul1, %mul2
    """

    _check_pre_post(pre, post)


def test_common_subexpression_elimination_no_commutative():
    pre = """
    main:
        %1 = param
        %sum1 = sub %1, 10
        %sum2 = sub 10, %1
        return %sum1, %sum2
    """

    _check_no_change(pre)


def test_common_subexpression_elimination_effects_1():
    pre = """
    main:
        %par = param
        %mload1 = mload 0
        mstore 0, %par
        %mload2 = mload 0
        %1 = add %mload1, 10
        %2 = add %mload2, 10
        return %1, %2
    """

    _check_no_change(pre)


def test_common_subexpression_elimination_effects_2():
    pre = """
    main:
        %par = param
        %mload1 = mload 0
        %1 = add %mload1, 10
        mstore 0, %par
        %mload2 = mload 0
        %2 = add %mload1, 10
        %3 = add %mload2, 10
        return %1, %2
    """

    post = """
    main:
        %par = param
        %mload1 = mload 0
        %1 = add %mload1, 10
        mstore 0, %par
        %mload2 = mload 0
        %2 = %1
        %3 = add %mload2, 10
        return %1, %2
    """

    _check_pre_post(pre, post)


def test_common_subexpression_elimination_logs_no_indepontent():
    pre = """
    main:
        %1 = 10
        log %1
        log %1
        stop
    """

    _check_no_change(pre)


def test_common_subexpression_elimination_effects_3():
    pre = """
    main:
        %addr = 10
        mstore %addr, 0
        mstore %addr, 2
        mstore %addr, 0
        stop
    """

    _check_no_change(pre)


def test_common_subexpression_elimination_effect_mstore():
    pre = """
    main:
        %1 = 10
        mstore 0, %1
        %mload1 = mload 0
        %2 = 10
        mstore 0, %1
        %mload2 = mload 0
        %res = add %mload1, %mload2
        return %res
    """

    post = """
    main:
        %1 = 10
        mstore 0, %1
        %mload1 = mload 0
        %2 = 10
        nop
        %mload2 = %mload1
        %res = add %mload1, %mload2
        return %res
    """

    _check_pre_post(pre, post)


def test_common_subexpression_elimination_effect_mstore_with_msize():
    pre = """
    main:
        %1 = 10
        mstore 0, %1
        %mload1 = mload 0
        %2 = 10
        mstore 0, %1
        %mload2 = mload 0
        %msize = msize
        %res1 = add %mload1, %msize
        %res2 = add %mload2, %msize
        return %res1, %res2
    """

    _check_no_change(pre)


def test_common_subexpression_elimination_different_branches_cannot_optimize():
    pre = """
    function main {
    main:
        ; random condition
        %par = param
        jnz @br1, @br2, %par
    br1:
        %a1 = add 10, 20
        %m1 = mul 1, %a1
        jmp @join
    br2:
        %a2 = add 10, 20
        %m2 = mul 2, %a2
        jmp @join
    join:
        %a3 = add 10, 20
        %m3 = mul 3, %a3
        return %m1, %m2, %m3
    }
    """

    _check_no_change_fn(pre)


def test_common_subexpression_elimination_different_branches_can_optimize():
    pre = """
    function main {
    main:
        ; random condition
        %par = param
        %d0 = mload 0
        %a0 = add 10, %d0
        %m0 = mul 0, %a0
        jnz @br1, @br2, %par
    br1:
        %d1 = mload 0
        %a1 = add 10, %d1
        %m1 = mul 1, %a1
        jmp @join
    br2:
        %d2 = mload 0
        %a2 = add 10, %d2
        %m2 = mul 2, %a2
        jmp @join
    join:
        %d3 = mload 0
        %a3 = add 10, %d3
        %m3 = mul 3, %a3
        return %m0, %m1, %m2, %m3
    }
    """

    post = """
    function main {
    main:
        ; random condition
        %par = param
        %d0 = mload 0
        %a0 = add 10, %d0
        %m0 = mul 0, %a0
        jnz @br1, @br2, %par
    br1:
        %d1 = mload 0
        %a1 = %a0
        %m1 = mul 1, %a1
        jmp @join
    br2:
        %d2 = mload 0
        %a2 = %a0
        %m2 = mul 2, %a2
        jmp @join
    join:
        %d3 = mload 0
        %a3 = %a0
        %m3 = mul 3, %a3
        return %m0, %m1, %m2, %m3
    }
    """

    _check_pre_post_fn(pre, post)
