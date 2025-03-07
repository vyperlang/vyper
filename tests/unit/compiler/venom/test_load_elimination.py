import pytest

from tests.venom_utils import PrePostChecker
from vyper.evm.address_space import CALLDATA, DATA, MEMORY, STORAGE, TRANSIENT
from vyper.venom.passes import LoadElimination, StoreElimination

pytestmark = pytest.mark.hevm

# the first store elimination is needed for
# variable equivalence in load elimination
# and the second/in post is needed to create
# easier equivalence in the test for pre and post
_check_pre_post = PrePostChecker(
    passes=[StoreElimination, LoadElimination, StoreElimination], post=[StoreElimination]
)


def _check_no_change(pre):
    _check_pre_post(pre, pre, hevm=False)


# fill memory with symbolic data for hevm
def _fill_symbolic(addrspace):
    if addrspace == MEMORY:
        return "calldatacopy 0, 0, 256"

    return ""


ADDRESS_SPACES = (MEMORY, STORAGE, TRANSIENT, CALLDATA, DATA)
RW_ADDRESS_SPACES = (MEMORY, STORAGE, TRANSIENT)


@pytest.mark.parametrize("addrspace", ADDRESS_SPACES)
def test_simple_load_elimination(addrspace):
    LOAD = addrspace.load_op
    pre = f"""
    main:
        %ptr = 11
        %1 = {LOAD} %ptr
        %2 = {LOAD} %ptr

        sink %1, %2
    """
    post = f"""
    main:
        %ptr = 11
        %1 = {LOAD} %ptr
        %2 = %1

        sink %1, %2
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("addrspace", ADDRESS_SPACES)
def test_equivalent_var_elimination(addrspace):
    """
    Test that the lattice can "peer through" equivalent vars
    """
    LOAD = addrspace.load_op
    pre = f"""
    main:
        %1 = 11
        %2 = %1

        %3 = {LOAD} %1
        %4 = {LOAD} %2

        sink %3, %4
    """
    post = f"""
    main:
        %1 = 11
        %2 = %1

        %3 = {LOAD} %1
        %4 = %3  # %2 == %1

        sink %3, %4
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


@pytest.mark.parametrize("addrspace", RW_ADDRESS_SPACES)
def test_store_load_elimination(addrspace):
    """
    Check that lattice stores the result of stores (even through
    equivalent variables)
    """
    LOAD = addrspace.load_op
    STORE = addrspace.store_op
    pre = f"""
    main:
        %val = 55
        %ptr1 = 11
        %ptr2 = %ptr1
        {STORE} %ptr1, %val

        %3 = {LOAD} %ptr2

        sink %3
    """
    post = f"""
        main:
        %val = 55
        %ptr1 = 11
        %ptr2 = %ptr1
        {STORE} %ptr1, %val

        %3 = %val

        sink %3
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

    pre = f"""
    main:
        {_fill_symbolic(MEMORY)}

        %ptr_mload = 10

        %tmp01 = mload %ptr_mload

        # this should not create barrier
        sstore %ptr_mload, 11
        %tmp02 = mload %ptr_mload

        sink %tmp01, %tmp02
    """

    post = f"""
    main:
        {_fill_symbolic(MEMORY)}

        %ptr_mload = 10

        %tmp01 = mload %ptr_mload

        # this should not create barrier
        sstore %ptr_mload, 11
        %tmp02 = %tmp01  ; mload optimized out

        sink %tmp01, %tmp02
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("addrspace", RW_ADDRESS_SPACES)
def test_store_store_no_overlap(addrspace):
    """
    Test that if the mstores do not overlap it can still
    eliminate any possible repeated mstores
    """
    LOAD = addrspace.load_op
    STORE = addrspace.store_op

    pre = f"""
    main:
        {_fill_symbolic(addrspace)}

        %ptr_mstore01 = 10
        %ptr_mstore02 = 42
        {STORE} %ptr_mstore01, 10

        {STORE} %ptr_mstore02, 11

        {STORE} %ptr_mstore01, 10

        %val1 = {LOAD} %ptr_mstore01
        %val2 = {LOAD} %ptr_mstore02
        sink %val1, %val2
    """

    post = f"""
    main:
        {_fill_symbolic(addrspace)}

        %ptr_mstore01 = 10
        %ptr_mstore02 = 42
        {STORE} %ptr_mstore01, 10

        {STORE} %ptr_mstore02, 11

        nop  ; repeated store

        sink 10, 11
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
