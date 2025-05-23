from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import LowerDloadPass

"""
test dload/dloadbytes -> codecopy pass
"""


def _check_pre_post(pre, post):
    ctx = parse_from_basic_block(pre)
    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        LowerDloadPass(ac, fn).run_pass()
    assert_ctx_eq(ctx, parse_from_basic_block(post))


def test_lower_dload_basic():
    pre = """
    main:
        %d1 = dload 100
        sink %d1
    """

    post = """
    main:
        %1 = add @code_end, 100
        codecopy 0, %1, 32
        %d1 = mload 0
        sink %d1
    """

    _check_pre_post(pre, post)


def test_lower_dload_var():
    """
    test that dload lowering pass lowers dload properly when the argument is a param
    """
    pre = """
    main:
        %par = param
        %d1 = dload %par
        sink %d1
    """

    post = """
    main:
        %par = param
        %1 = add @code_end, %par
        codecopy 0, %1, 32
        %d1 = mload 0
        sink %d1
    """

    _check_pre_post(pre, post)


def test_lower_dload_dloadbytes():
    """
    test that dload lowering pass lowers dloadbytes instruction
    """
    pre = """
    main:
        %par = param
        dloadbytes 100, 200, 50
        dloadbytes 300, %par, 50
        stop
    """

    post = """
    main:
        %par = param
        %1 = add @code_end, 200
        codecopy 100, %1, 50
        %2 = add @code_end, %par
        codecopy 300, %2, 50
        stop
    """

    _check_pre_post(pre, post)
