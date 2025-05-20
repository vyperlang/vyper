from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes import AssignElimination, DFTPass, SimplifyCFGPass, SingleUseExpansion
from vyper.venom.venom_to_assembly import VenomCompiler

# assing elim is there to have easier check
_check_pre_post = PrePostChecker([SingleUseExpansion, DFTPass, AssignElimination])


def test_stack_order_basic():
    pre = """
    main:
        %1 = mload 1
        %2 = mload 2
        jmp @next
    next:
        %3 = add 1, %1
        %4 = add 1, %2
        return %4, %3
    """

    post = """
    main:
        %2 = mload 2
        %1 = mload 1
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
        "MLOAD",
        "PUSH1",
        1,
        "MLOAD",
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
        %1 = mload 1
        %2 = mload 2
        jmp @next
    next:
        %3 = add 1, %1
        %4 = add 1, %2
        return %3, %4
    """

    post = """
    main:
        %1 = mload 1
        %2 = mload 2
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
        "MLOAD",
        "PUSH1",
        2,
        "MLOAD",
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
