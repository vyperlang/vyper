from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes import RemoveUnusedVariablesPass


def _check_pre_post(pre, post):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_removeunused_basic():
    """
    Check basic unused variable removal
    """
    pre = """
    main:
        %1 = add 10, 20
        %2_unused = add 10, %1
        mstore 20, %1
        stop
    """
    post = """
    main:
        %1 = add 10, 20
        mstore 20, %1
        stop
    """
    _check_pre_post(pre, post)


def test_removeunused_chain():
    """
    Check removal of unused variable dependency chain
    """
    pre = """
    main:
        %1 = add 10, 20
        %2_unused = add 10, %1
        %3_unused = add 10, %2_unused
        mstore 20, %1
        stop
    """
    post = """
    main:
        %1 = add 10, 20
        mstore 20, %1
        stop
    """
    _check_pre_post(pre, post)


def test_removeunused_loop():
    """
    Test unused variable removal in loop
    """
    pre = """
    main:
        %1 = 10
        jmp @after
    after:
        %p = phi @main, %1, @after, %2
        %2 = add %p, 1
        %3_unused = add %2, %p
        mstore 10, %2
        jmp @after
    """
    post = """
    main:
        %1 = 10
        jmp @after
    after:
        %p = phi @main, %1, @after, %2
        %2 = add %p, 1
        mstore 10, %2
        jmp @after
    """
    _check_pre_post(pre, post)


def test_removeunused_mload_basic():
    pre = """
    main:
        itouch 32
        %b = msize
        %c_unused = mload 64  # safe to remove
        return %b, %b
    """
    post = """
    main:
        itouch 32
        %b = msize
        return %b, %b
    """
    _check_pre_post(pre, post)


def test_removeunused_mload_two_msizes():
    pre = """
    main:
        %a = mload 32
        %b = msize
        %c = mload 64
        %d = msize
        return %b, %d
    """
    post = """
    main:
        %b = msize
        %d = msize
        return %b, %d
    """
    _check_pre_post(pre, post)


def test_removeunused_msize_loop():
    pre = """
    main:
        %1 = msize
        itouch %1  # volatile
        jmp @main
    """
    _check_no_change(pre)


def test_remove_unused_mload_msize():
    """
    Test removal of non-volatile mload and msize instructions
    """
    pre = """
    main:
        %1_unused = mload 10
        %2_unused = msize
        stop
    """
    post = """
    main:
        stop
    """
    _check_pre_post(pre, post)


def test_remove_unused_mload_msize_chain_loop():
    """
    Test removal of non-volatile mload and msize instructions.
    Loop version
    """
    pre = """
    main:
        %1_unused = msize
        %2_unused = mload 10
        jmp @main
    """
    post = """
    main:
        jmp @main
    """
    _check_pre_post(pre, post)
