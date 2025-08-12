import pytest

from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes import AssignElimination, DFTPass, SimplifyCFGPass, SingleUseExpansion
from vyper.venom.venom_to_assembly import VenomCompiler

# assing elim is there to have easier check
_check_pre_post = PrePostChecker([SingleUseExpansion, DFTPass, AssignElimination])


def _check_no_change(pre):
    _check_pre_post(pre, pre, hevm=False)


def test_stack_order_basic():
    pre = """
    main:
        %1 = calldataload 1
        %2 = calldataload 2
        jmp @next
    next:
        %3 = add 1, %1
        %4 = add 1, %2
        return %4, %3
    """

    post = """
    main:
        %2 = calldataload 2
        %1 = calldataload 1
        jmp @next
    next:
        %3 = add 1, %1
        %4 = add 1, %2
        return %4, %3
    """

    _check_pre_post(pre, post)

    ctx = parse_from_basic_block(post)
    for fn in ctx.get_functions():
        ac = IRAnalysesCache(fn)
        SingleUseExpansion(ac, fn).run_pass()
        SimplifyCFGPass(ac, fn).run_pass()

    print(ctx)

    asm = VenomCompiler([ctx]).generate_evm()
    print(asm)
    assert asm == [
        "PUSH1",
        2,
        "CALLDATALOAD",
        "PUSH1",
        1,
        "CALLDATALOAD",
        "PUSH1",
        1,
        "ADD",
        "SWAP1",  # swap out the result of the first add (only necessary swap)
        "PUSH1",
        1,
        "ADD",
        "RETURN",
    ]


def test_stack_order_basic2():
    pre = """
    main:
        %1 = calldataload 1
        %2 = calldataload 2
        jmp @next
    next:
        %3 = add 1, %1
        %4 = add 1, %2
        return %3, %4
    """

    post = """
    main:
        %1 = calldataload 1
        %2 = calldataload 2
        jmp @next
    next:
        %4 = add 1, %2
        %3 = add 1, %1
        return %3, %4
    """

    _check_pre_post(pre, post)

    ctx = parse_from_basic_block(post)
    for fn in ctx.get_functions():
        ac = IRAnalysesCache(fn)
        SingleUseExpansion(ac, fn).run_pass()
        SimplifyCFGPass(ac, fn).run_pass()

    print(ctx)

    asm = VenomCompiler([ctx]).generate_evm()
    print(asm)
    assert asm == [
        "PUSH1",
        1,
        "CALLDATALOAD",
        "PUSH1",
        2,
        "CALLDATALOAD",
        "PUSH1",
        1,
        "ADD",
        "SWAP1",  # swap out the result of the first add (only necessary swap)
        "PUSH1",
        1,
        "ADD",
        "RETURN",
    ]


def test_stack_order_split():
    pre = """
    main:
        %1 = mload 1
        %2 = mload 2
        %3 = add 1, %2
        %cond = mload 3
        jnz %cond, @then, @else
    then:
        %4a = add 1, %1
        %5a = add 1, %3
        sink %5a, %4a
    else:
        %4b = add 1, %1
        %5b = add 1, %3
        sink %5b, %4b
    """

    post = """
    main:
        %2 = mload 2
        %3 = add 1, %2
        %1 = mload 1
        %cond = mload 3
        jnz %cond, @then, @else
    then:
        %4a = add 1, %1
        %5a = add 1, %3
        sink %5a, %4a
    else:
        %4b = add 1, %1
        %5b = add 1, %3
        sink %5b, %4b
    """

    _check_pre_post(pre, post)


def test_stack_order_split2():
    pre = """
    main:
        %1 = mload 1
        %2 = mload 2
        %3 = add 1, %2
        %cond = mload 3
        jnz %cond, @then, @else
    then:
        %4a = add 1, %1
        %5a = add 1, %2
        sink %5a, %4a
    else:
        %4b = add 1, %1
        %5b = add 1, %3
        sink %5b, %4b
    """

    post = """
    main:
        %2 = mload 2
        %3 = add 1, %2
        %1 = mload 1
        %cond = mload 3
        jnz %cond, @then, @else
    then:
        %4a = add 1, %1
        %5a = add 1, %2
        sink %5a, %4a
    else:
        %4b = add 1, %1
        %5b = add 1, %3
        sink %5b, %4b
    """

    _check_pre_post(pre, post)


def test_stack_order_join():
    pre = """
    main:
        %cond = param
        %1 = mload 1
        %2 = mload 2
        jnz %cond, @then, @else
    then:
        %3a = mload 3
        mstore 1000, %3a
        jmp @join
    else:
        %3b = mload 3
        mstore 2000, %3b
        jmp @join
    join:
        sink %1
    """

    post = """
    main:
        %cond = param
        %2 = mload 2
        %1 = mload 1
        jnz %cond, @then, @else
    then:
        %3a = mload 3
        mstore 1000, %3a
        jmp @join
    else:
        %3b = mload 3
        mstore 2000, %3b
        jmp @join
    join:
        sink %1
    """

    _check_pre_post(pre, post)


def test_stack_order_join_unmergable_stacks():
    pre = """
    main:
        %cond = param
        %1 = mload 1
        %2 = mload 2
        jnz %cond, @then, @else
    then:
        mstore 1000, %1
        jmp @join
    else:
        mstore 2000, %2
        jmp @join
    join:
        sink %1
    """

    _check_no_change(pre)


def test_stack_order_phi():
    pre = """
    main:
        %par = param
        jnz %par, @then, @else
    then:
        %1a = add 1, %par
        %2a = mload 10
        mstore 1000, %2a
        jmp @join
    else:
        %1b = add 2, %par
        %2b = mload 10
        mstore 1000, %2b
        jmp @join
    join:
        %1 = phi @then, %1a, @else, %1b
        %res = add 1, %1 ; properly use the value
        sink %res
    """

    post = """
    main:
        %par = param
        jnz %par, @then, @else
    then:
        %2a = mload 10
        mstore 1000, %2a
        %1a = add 1, %par
        jmp @join
    else:
        %2b = mload 10
        mstore 1000, %2b
        %1b = add 2, %par
        jmp @join
    join:
        %1 = phi @then, %1a, @else, %1b
        %res = add 1, %1 ; properly use the value
        sink %res
    """

    _check_pre_post(pre, post)


# TODO: fix this xfail before merge
#@pytest.mark.xfail
def test_stack_order_more_phi():
    pre = """
    main:
        %par = param
        jnz %par, @then, @else
    then:
        %1a = add 1, %par
        %2a = add 2, %par
        jmp @join
    else:
        %1b = add 3, %par
        %2b = add 4, %par
        jmp @join
    join:
        %2 = phi @then, %2a, @else, %2b
        %1 = phi @then, %1a, @else, %1b
        %res1 = add 1, %1 ; properly use the value
        %res2 = add 1, %2 ; properly use the value
        sink %res2, %res1
    """

    post = """
    main:
        %par = param
        jnz %par, @then, @else
    then:
        %2a = add 2, %par
        %1a = add 1, %par
        jmp @join
    else:
        %2b = add 4, %par
        %1b = add 3, %par
        jmp @join
    join:
        %2 = phi @then, %2a, @else, %2b
        %1 = phi @then, %1a, @else, %1b
        %res1 = add 1, %1 ; properly use the value
        %res2 = add 1, %2 ; properly use the value
        sink %res2, %res1
    """

    _check_pre_post(pre, post)


def test_stack_order_entry_instruction():
    pre = """
    main:
        %p = param
        %1 = add %p, 1
        assert %1
        %2 = add %p, 2
        %cond = iszero %p
        jnz %cond, @then, @else
    then:
        %3a = mload 0
        mstore 100, %3a
        jmp @join
    else:
        %3b = mload 0
        mstore 100, %3b
        jmp @join
    join:
        sink %1, %2
    """

    post = """
    main:
        %p = param
        %2 = add %p, 2
        %cond = iszero %p
        %1 = add %p, 1
        assert %1
        jnz %cond, @then, @else
    then:
        %3a = mload 0
        mstore 100, %3a
        jmp @join
    else:
        %3b = mload 0
        mstore 100, %3b
        jmp @join
    join:
        sink %1, %2
    """
    
    _check_pre_post(pre, post)

def test_stack_order_two_trees():
    pre = """
    main:
        %1 = param
        %2 = param
        %cond = iszero %2
        assert %cond
        %3 = 3
        jmp @after
    after:
        sink %3, %2, %1
    """

    _check_no_change(pre)
