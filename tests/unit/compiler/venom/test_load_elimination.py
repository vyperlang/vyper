from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes.load_elimination import LoadElimination


def _check_pre_post(pre, post):
    ctx = parse_from_basic_block(pre)

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        LoadElimination(ac, fn).run_pass()

    assert_ctx_eq(ctx, parse_from_basic_block(post))


def _check_no_change(pre):
    _check_pre_post(pre, pre)


def test_simple_load_elimination():
    pre = """
    main:
        %ptr = 11
        %1 = mload %ptr

        %2 = mload %ptr

        stop
    """
    post = """
    main:
        %ptr = 11
        %1 = mload %ptr

        %2 = %1

        stop
    """
    _check_pre_post(pre, post)


def test_equivalent_var_elimination():
    """
    Test that the lattice can "peer through" equivalent vars
    """
    pre = """
    main:
        %1 = 11
        %2 = %1
        %3 = mload %1

        %4 = mload %2

        stop
    """
    post = """
    main:
        %1 = 11
        %2 = %1
        %3 = mload %1

        %4 = %3  # %2 == %1

        stop
    """
    _check_pre_post(pre, post)


def test_elimination_barrier():
    """
    Check for barrier between load/load
    """
    pre = """
    main:
        %1 = 11
        %2 = mload %1
        %3 = %100
        # fence - writes to memory
        staticcall %3, %3, %3, %3
        %4 = mload %1
    """
    _check_no_change(pre)


def test_store_load_elimination():
    """
    Check that lattice stores the result of mstores (even through
    equivalent variables)
    """
    pre = """
    main:
        %val = 55
        %ptr1 = 11
        %ptr2 = %ptr1
        mstore %ptr1, %val

        %3 = mload %ptr2

        stop
    """
    post = """
        main:
        %val = 55
        %ptr1 = 11
        %ptr2 = %ptr1
        mstore %ptr1, %val

        %3 = %val

        stop
    """
    _check_pre_post(pre, post)


def test_store_load_barrier():
    """
    Check for barrier between store/load
    """
    pre = """
    main:
        %ptr = 11
        %val = 55
        mstore %ptr, %val
        %3 = %100  ; arbitrary
        # fence
        staticcall %3, %3, %3, %3
        %4 = mload %ptr
    """
    _check_no_change(pre)
