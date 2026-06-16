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
