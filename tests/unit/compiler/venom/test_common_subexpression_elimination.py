import pytest

from tests.hevm import hevm_check_venom
from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes.common_subexpression_elimination import CSE

pytestmark = pytest.mark.hevm


def _check_pre_post(pre: str, post: str, hevm: bool = True):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        CSE(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_from_basic_block(post))

    if not hevm:
        return

    hevm_check_venom(pre, post)


def _check_no_change(pre: str, hevm: bool = True):
    _check_pre_post(pre, pre, hevm)


def test_cse_basic():
    pre = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = add %1, 10
        %mul2 = mul %sum2, 10
        sink %mul1, %mul2
    """

    post = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = %sum1
        %mul2 = %mul1
        sink %mul1, %mul2
    """

    _check_pre_post(pre, post)


def test_cse_commutative():
    pre = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = add 10, %1
        %mul2 = mul 10, %sum2
        sink %mul1, %mul2
    """

    post = """
    main:
        %1 = param
        %sum1 = add %1, 10
        %mul1 = mul %sum1, 10
        %sum2 = %sum1
        %mul2 = %mul1
        sink %mul1, %mul2
    """

    _check_pre_post(pre, post)


def test_cse_no_commutative():
    """
    Tests you cannot substitute cummutated non-cumutative operations
    """
    pre = """
    main:
        %1 = param
        %sum1 = sub %1, 10
        %sum2 = sub 10, %1
        sink %sum1, %sum2
    """

    _check_no_change(pre)


def test_cse_effects_1():
    """
    Test that inner dependencies have correct barrier
    """
    pre = """
    main:
        %par = param
        %mload1 = mload 0

        ; barrier
        mstore 0, %par
        %mload2 = mload 0

        ; adds cannot be substituted because the
        ; mloads are separated with barrier
        %1 = add %mload1, 10
        %2 = add %mload2, 10
        sink %1, %2
    """

    _check_no_change(pre)


def test_cse_effects_2():
    """
    Test that barrier does not affect inner dependencies
    """
    pre = """
    main:
        %par = param
        %mload1 = mload 0
        %1 = add %mload1, 10

        ; barrier
        mstore 0, %par
        %mload2 = mload 0

        ; mload1 is still valid and same
        %2 = add %mload1, 10

        ; this cannot be substituted since mload1
        ; and mload2 are separated by barrier
        %3 = add %mload2, 10
        sink %1, %2
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
        sink %1, %2
    """

    _check_pre_post(pre, post)


def test_cse_logs_no_indepontent():
    pre = """
    main:
        %1 = 10
        log %1
        log %1
        stop
    """

    _check_no_change(pre, hevm=False)


def test_cse_effects_3():
    """
    Test of memory effects that contains barrier that
    prevents substitution
    """
    pre = """
    main:
        %addr = 10
        mstore %addr, 0
        mstore %addr, 2 ; barrier
        mstore %addr, 0
        stop
    """

    _check_no_change(pre)


def test_cse_effect_mstore():
    """
    Test mload and mstore elimination if they are
    same expression
    """
    pre = """
    main:
        %1 = 10
        mstore 0, %1
        %mload1 = mload 0
        %2 = 10
        mstore 0, %1
        %mload2 = mload 0
        %res = add %mload1, %mload2
        sink %res
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
        sink %res
    """

    _check_pre_post(pre, post)


def test_cse_effect_mstore_with_msize():
    """
    Test that checks that msize is handled correctly
    """
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
        sink %res1, %res2
    """

    _check_no_change(pre)


def test_cse_different_branches_cannot_optimize():
    """
    Test of inter basicblock analysis which would require
    more code movement to achive and would be incorrect
    if done the current way
    """

    def same(i):
        return f"""
        %d{i} = mload 0
        %a{i} = add 10, %d{i}
        %m{i} = mul {i}, %a{i}
        """

    pre = f"""
    main:
        ; random condition
        %par = param
        jnz %par, @br1, @br2
    br1:
        {same(1)}
        jmp @join
    br2:
        {same(2)}
        jmp @join
    join:
        %m = phi @br1, %m1, @br2, %m2
        ; here you  cannot guarantee which
        ; branch this expression came from
        ; so you cannot substitute
        {same(3)}
        sink %m, %m3
    """

    _check_no_change(pre)


def test_cse_different_branches_can_optimize():
    """
    Test of inter basicblock analysis
    """

    def same(i):
        return f"""
        %d{i} = mload 0
        %a{i} = add 10, %d{i}
        %m{i} = mul {i}, %a{i}
        """

    def same_opt(i):
        return f"""
        %d{i} = mload 0
        %a{i} = %a0
        %m{i} = mul {i}, %a{i}
        """

    pre = f"""
    main:
        ; random condition
        %par = param
        {same(0)}
        jnz @br1, @br2, %par
    br1:
        {same(1)}
        jmp @join
    br2:
        {same(2)}
        jmp @join
    join:
        %m = phi @br1, %m1, @br2, %m2
        {same(3)}
        sink %m0, %m3, %m
    """

    post = f"""
    main:
        ; random condition
        %par = param
        {same(0)}
        jnz @br1, @br2, %par
    br1:
        {same_opt(1)}
        jmp @join
    br2:
        {same_opt(2)}
        jmp @join
    join:
        %m = phi @br1, %m1, @br2, %m2
        {same_opt(3)}
        sink %m0, %m3, %m
    """

    _check_pre_post(pre, post)


def test_cse_invoke_idempotent():
    pre = """
    main:
        ; invoke
        %invoke0 = invoke @f
        %i0 = add 1, %invoke0
        %invoke1 = invoke @f
        %i1 = add 1, %invoke1
        sink %i0, %i1
    """

    _check_no_change(pre, hevm=False)


def test_cse_non_idempotent():
    """
    Test to check if the instruction that cannot be substituted
    are not substituted with pass and any instruction that would
    use non indempotent instruction also cannot be substituted
    """

    def call(callname: str, i: int, var_name: str):
        return f"""
        %g{2*i} = gas
        %{callname}0 = {callname} %g0, 0, 0, 0, 0, 0
        %{var_name}0 = add 1, %{callname}0
        %g{2*i + 1} = gas
        %{callname}1 = {callname} %g0, 0, 0, 0, 0, 0
        %{var_name}1 = add 1, %{callname}1
        """

    pre = f"""
    main:
        ; staticcall
        {call("staticcall", 0, "s")}

        ; delegatecall
        {call("delegatecall", 1, "d")}

        ; call
        {call("call", 2, "c")}
        sink %s0, %s1, %d0, %d1, %c0, %c1
    """

    _check_no_change(pre)


@pytest.mark.xfail
def test_cse_loop():
    """
    Test of inter basic block common subexpression
    elimination with loops
    """

    pre = """
    main:
        %par = param
        %data0 = mload 0
        %add0 = add 1, %par
        %mul0 = mul %add0, %data0
        jmp @loop
    loop:
        %data1 = mload 0
        %add1 = add 1, %par
        %mul1 = mul %add1, %data1
        jmp @loop
    """

    post = """
    main:
        %par = param
        %data0 = mload 0
        %add0 = add 1, %par
        %mul0 = mul %add0, %data0
        jmp @loop
    loop:
        %data1 = mload 0
        %add1 = %add0
        %mul1 = %mul0
        jmp @loop
    """

    _check_pre_post(pre, post)


def test_cse_loop_cannot_substitute():
    """
    Test of inter basic block common subexpression
    elimination with loops, which contains barrier
    that prevents part of substitution
    """

    pre = """
    main:
        %par = param
        %data0 = mload 0
        %add0 = add 1, %par
        %mul0 = mul %add0, %data0
        jmp @loop
    loop:
        %data1 = mload 0
        %add1 = add 1, %par
        %mul1 = mul %add1, %data1

        ; barrier
        mstore 10, 0
        jmp @loop
    """

    _check_no_change(pre)


@pytest.mark.parametrize("opcode", ("calldatasize", "gaslimit", "address", "codesize"))
def test_cse_immutable_queries(opcode):
    """
    Test that check that instruction that have always same
    output during the function execution are considered
    same in analysis
    """

    pre = f"""
    main:
        %1 = {opcode}
        %res1 = add %1, 1
        %2 = {opcode}
        %res2 = add %1, 1
        sink %res1, %res2
    """

    post = f"""
    main:
        %1 = {opcode}
        %res1 = add %1, 1
        %2 = {opcode}
        %res2 = %res1
        sink %res1, %res2
    """

    # the codesize will be for sure different size
    # result of code is dependant on code which will
    # be different
    _check_pre_post(pre, post, hevm=opcode != "codesize")


@pytest.mark.parametrize(
    "opcode", ("dloadbytes", "extcodecopy", "codecopy", "returndatacopy", "calldatacopy")
)
def test_cse_other_mem_ops_elimination(opcode):
    pre = f"""
    main:
        {opcode} 10, 20, 30
        {opcode} 10, 20, 30
        stop
    """

    post = f"""
    main:
        {opcode} 10, 20, 30
        nop
        stop
    """

    _check_pre_post(pre, post)


def test_cse_self_conflicting_effects():
    """
    Test that expression that have conflict in their own effects
    cannot be substituted
    """
    pre1 = """
    main:
        mcopy 10, 100, 10
        mcopy 10, 100, 10
        stop
    """

    pre2 = """
    main:
        %load1 = mload 0
        mstore 1000, %load1
        %load2 = mload 0
        mstore 1000, %load2
        stop
    """

    _check_no_change(pre1)
    _check_no_change(pre2)


def test_cse_allowed_deep_self_conflict():
    pre = """
    main:
        %load1 = mload 0
        mstore 1000, %load1
        mstore 1000, %load1
        stop
    """

    post = """
    main:
        %load1 = mload 0
        mstore 1000, %load1
        nop
        stop
    """

    _check_pre_post(pre, post)


def test_cse_small_expressions():
    pre = """
    main:
        %par = param
        %1 = add 1, 2
        jnz %par, @then, @else
    then:
        %2 = add 1, 2
        %3 = add 1, 2
        jmp @join
    else:
        %4 = add 1, 2
        jmp @join
    join:
        %5 = add 1, 2
        sink %5
    """

    post = """
    main:
        %par = param
        %1 = add 1, 2
        jnz %par, @then, @else
    then:
        %2 = add 1, 2
        %3 = %2
        jmp @join
    else:
        %4 = add 1, 2
        jmp @join
    join:
        %5 = add 1, 2
        sink %5
    """

    _check_pre_post(pre, post)


def test_cse_different_params():
    pre = """
    main:
        %p1 = param
        %p2 = param
        %a1 = add %p1, %p2
        %a2 = add %p2, %p2
        sink %a1, %a2
    """

    _check_no_change(pre)
