from tests.venom_utils import assert_ctx_eq, parse_from_basic_block
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.passes.load_elimination import LoadElimination
from vyper.venom.passes.store_elimination import StoreElimination


def _check_pre_post(pre, post):
    ctx = parse_from_basic_block(pre)

    post_ctx = parse_from_basic_block(post)
    for fn in post_ctx.functions.values():
        ac = IRAnalysesCache(fn)
        # this store elim is used for
        # proper equivalence of the post
        # and pre results
        StoreElimination(ac, fn).run_pass()

    for fn in ctx.functions.values():
        ac = IRAnalysesCache(fn)
        # store elim is needed for variable equivalence
        StoreElimination(ac, fn).run_pass()
        LoadElimination(ac, fn).run_pass()
        # this store elim is used for
        # proper equivalence of the post
        # and pre results
        StoreElimination(ac, fn).run_pass()

    assert_ctx_eq(ctx, post_ctx)


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


def test_store_load_overlap_barrier():
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = """
    main:
        %ptr_mload = 10
        %ptr_mstore = 20
        %tmp01 = mload %ptr_mload

        # barrier created with overlap
        mstore %ptr_mstore, 11
        %tmp02 = mload %ptr_mload
        return %tmp01, %tmp02
    """

    _check_no_change(pre)


def test_store_store_overlap_barrier():
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = """
    main:
        %ptr_mstore01 = 10
        %ptr_mstore02 = 20
        mstore %ptr_mstore01, 10

        # barrier created with overlap
        mstore %ptr_mstore02, 11

        mstore %ptr_mstore01, 10
        stop
    """

    _check_no_change(pre)


def test_store_load_no_overlap_different_store():
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = """
    main:
        %ptr_mload = 10
        %tmp01 = mload %ptr_mload

        # this should not create barrier
        sstore %ptr_mload, 11
        %tmp02 = mload %ptr_mload
        return %tmp01, %tmp02
    """

    post = """
    main:
        %ptr_mload = 10
        %tmp01 = mload %ptr_mload

        # this should not create barrier
        sstore %ptr_mload, 11
        %tmp02 = %tmp01
        return %tmp01, %tmp02
    """

    _check_pre_post(pre, post)


def test_store_store_no_overlap():
    """
    Test that if the mstores do not overlap it can still
    eliminate any possible repeated mstores
    """

    pre = """
    main:
        %ptr_mstore01 = 10
        %ptr_mstore02 = 42
        mstore %ptr_mstore01, 10

        mstore %ptr_mstore02, 11

        mstore %ptr_mstore01, 10
        stop
    """

    post = """
    main:
        %ptr_mstore01 = 10
        %ptr_mstore02 = 42
        mstore %ptr_mstore01, 10

        mstore %ptr_mstore02, 11

        nop
        stop
    """

    _check_pre_post(pre, post)


def test_store_store_unknown_ptr_barrier():
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = """
    main:
        %ptr_mstore01 = 10
        %ptr_mstore02 = param
        mstore %ptr_mstore01, 10

        # barrier created with overlap
        mstore %ptr_mstore02, 11

        mstore %ptr_mstore01, 10
        stop
    """

    _check_no_change(pre)
