import pytest

from tests.hevm import hevm_check_venom_ctx
from tests.venom_utils import assert_ctx_eq, parse_from_basic_block, parse_venom
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import MakeSSA


def _check_pre_post(pre, post):
    ctx = parse_venom(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_venom(post))


def test_phi_case():
    pre = """
    function loop {
    main:
        %v = mload 64
        jmp @test
    test:
        jnz %v, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @continue
    else:
        jmp @continue
    continue:
        %v = add %v, 1
        jmp @test
    }
    """
    post = """
    function loop {
    main:
        %v = mload 64
        jmp @test
    test:
        %v:1 = phi @main, %v, @continue, %v:2
        jnz %v:1, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @continue
    else:
        jmp @continue
    continue:
        %v:2 = add %v:1, 1
        jmp @test
    }
    """
    _check_pre_post(pre, post)


def test_multiple_make_ssa_error():
    pre = """
    main:
        %v = mload 64
        jmp @test
    test:
        jnz %v, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @if_exit
    else:
        jmp @if_exit
    if_exit:
        %v = add %v, 1
        jmp @test
    """

    post = """
    main:
        %v = mload 64
        jmp @test
    test:
        %v:1:1 = phi @main, %v, @if_exit, %v:2
        jnz %v:1:1, @then, @else
    then:
        %t = mload 96
        assert %t
        jmp @if_exit
    else:
        jmp @if_exit
    if_exit:
        %v:2 = add %v:1:1, 1
        jmp @test
    """

    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


@pytest.mark.hevm
def test_make_ssa_error():
    code = """
    main:
        %cond = param
        %v = 0
        jnz %cond, @then, @else
    then:
        %v = 1
        jnz 1, @join, @unreachable
    unreachable:
        %v = 100
        jmp @join
    else:
        %v = 2
        jmp @join
    join:
        sink %v
    """

    ctx = parse_from_basic_block(code)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        MakeSSA(ac, fn).run_pass()
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    post_ctx = parse_from_basic_block(code)
    for fn in post_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        # Mem2Var(ac, fn).run_pass()
        MakeSSA(ac, fn).run_pass()
        # RemoveUnusedVariablesPass(ac, fn).run_pass()

    hevm_check_venom_ctx(ctx, post_ctx)
