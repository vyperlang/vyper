import pytest

from tests.venom_utils import PrePostChecker
from vyper.evm.address_space import CALLDATA, DATA, MEMORY, STORAGE, TRANSIENT
from vyper.venom.passes import AssignElimination, LoadElimination

pytestmark = pytest.mark.hevm

# the first store elimination is needed for
# variable equivalence in load elimination
# and the second/in post is needed to create
# easier equivalence in the test for pre and post
_check_pre_post = PrePostChecker(
    passes=[AssignElimination, LoadElimination, AssignElimination], post=[AssignElimination]
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


@pytest.mark.parametrize("position", [11, "alloca 32"])  # noqa: FS003
@pytest.mark.parametrize("addrspace", ADDRESS_SPACES)
def test_simple_load_elimination(addrspace, position):
    if addrspace != MEMORY and not isinstance(position, int):
        return

    LOAD = addrspace.load_op
    pre = f"""
    main:
        %ptr = {position}
        %1 = {LOAD} %ptr
        %2 = {LOAD} %ptr

        sink %1, %2
    """
    post = f"""
    main:
        %ptr = {position}
        %1 = {LOAD} %ptr
        %2 = %1

        sink %1, %2
    """
    _check_pre_post(pre, post)


@pytest.mark.parametrize("position", [11, "alloca 32"])  # noqa: FS003
@pytest.mark.parametrize("addrspace", ADDRESS_SPACES)
def test_equivalent_var_elimination(addrspace, position):
    """
    Test that the lattice can "peer through" equivalent vars
    """
    if addrspace != MEMORY and not isinstance(position, int):
        return

    LOAD = addrspace.load_op
    pre = f"""
    main:
        %1 = {position}
        %2 = %1

        %3 = {LOAD} %1
        %4 = {LOAD} %2

        sink %3, %4
    """
    post = f"""
    main:
        %1 = {position}
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
        staticcall %3, %3, %3, %3, %3, %3
        %4 = mload %1
        stop
    """
    _check_no_change(pre)


@pytest.mark.parametrize("position", [[55, 11], [55, "alloca 32"]])  # noqa: FS003
@pytest.mark.parametrize("addrspace", RW_ADDRESS_SPACES)
def test_store_load_elimination(addrspace, position: list):
    """
    Check that lattice stores the result of stores (even through
    equivalent variables)
    """
    if addrspace != MEMORY and not isinstance(position, int):
        return

    LOAD = addrspace.load_op
    STORE = addrspace.store_op

    val, ptr = position

    pre = f"""
    main:
        %val = {val}
        %ptr1 = {ptr}
        %ptr2 = %ptr1
        {STORE} %ptr1, %val

        %3 = {LOAD} %ptr2

        sink %3
    """
    post = f"""
        main:
        %val = {val}
        %ptr1 = {ptr}
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
        staticcall %3, %3, %3, %3, %3, %3
        %4 = mload %ptr
        stop
    """
    _check_no_change(pre)


@pytest.mark.parametrize("position", [(10, 20), (32, 63)])
def test_store_load_overlap_barrier(position: tuple):
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    ptr_mload, ptr_mstore = position

    pre = f"""
    main:
        %ptr_mload = {ptr_mload}
        %ptr_mstore = {ptr_mstore}
        %tmp01 = mload %ptr_mload

        # barrier created with overlap
        mstore %ptr_mstore, 11
        %tmp02 = mload %ptr_mload
        return %tmp01, %tmp02
    """

    _check_no_change(pre)


def test_store_load_pair_memloc():
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = """
    main:
        %ptr_mload = alloca 32
        %ptr_mstore = alloca 32
        %tmp01 = mload %ptr_mload

        # barrier created with overlap
        mstore %ptr_mstore, 11
        %tmp02 = mload %ptr_mload
        return %tmp01, %tmp02
    """
    post = """
    main:
        %ptr_mload = alloca 32
        %ptr_mstore = alloca 32
        %tmp01 = mload %ptr_mload

        # barrier created with overlap
        mstore %ptr_mstore, 11
        return %tmp01, %tmp01
    """  # noqa: FS003

    _check_pre_post(pre, post)


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


@pytest.mark.parametrize("position", [(10, 42), ("alloca 32", "alloca 32")])  # noqa: FS003
@pytest.mark.parametrize("addrspace", RW_ADDRESS_SPACES)
def test_store_store_no_overlap(addrspace, position: tuple):
    """
    Test that if the mstores do not overlap it can still
    eliminate any possible repeated mstores
    """
    ptr_1, ptr_2 = position
    if addrspace != MEMORY and not isinstance(ptr_1, int):
        return

    LOAD = addrspace.load_op
    STORE = addrspace.store_op

    pre = f"""
    main:
        {_fill_symbolic(addrspace)}

        %ptr_mstore01 = {ptr_1}
        %ptr_mstore02 = {ptr_2}
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

        %ptr_mstore01 = {ptr_1}
        %ptr_mstore02 = {ptr_2}
        {STORE} %ptr_mstore01, 10

        {STORE} %ptr_mstore02, 11

        nop  ; repeated store

        sink 10, 11
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("position", [10, "alloca 32"])  # noqa: FS003
def test_store_store_unknown_ptr_barrier(position: list):
    """
    Check for barrier between store/load done
    by overlap of the mstore and mload
    """

    pre = f"""
    main:
        %ptr_mstore01 = {position}
        %ptr_mstore02 = source
        mstore %ptr_mstore01, 10

        # barrier created with overlap
        mstore %ptr_mstore02, 11

        mstore %ptr_mstore01, 10
        stop
    """

    _check_no_change(pre)


@pytest.mark.parametrize("position", [5, "alloca 32"])  # noqa: FS003
def test_simple_load_elimination_inter(position):
    pre = f"""
    main:
        %par = param
        %ptr = {position}
        %1 = mload %ptr
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        jmp @join
    else:
        jmp @join
    join:
        %3 = mload %ptr
        sink %3
    """

    post = f"""
    main:
        %par = param
        %ptr = {position}
        %1 = mload %ptr
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        jmp @join
    else:
        jmp @join
    join:
        %3 = %1
        sink %3
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("position", [5, "alloca 32"])  # noqa: FS003
def test_simple_load_elimination_inter_join(position):
    pre = f"""
    main:
        %par = param
        %ptr = {position}
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload %ptr
        jmp @join
    else:
        %2 = mload %ptr
        jmp @join
    join:
        %3 = mload %ptr
        sink %3
    """

    post = f"""
    main:
        %par = param
        %ptr = {position}
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload %ptr
        jmp @join
    else:
        %2 = mload %ptr
        jmp @join
    join:
        %4 = phi @then, %1, @else, %2
        %3 = %4
        sink %3
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize(
    "position", [(5, 1000, 50), ("alloc 32", "alloca 32", "alloca 32")]  # noqa: FS003
)
def test_load_elimination_inter_distant_bb(position):
    a, b, c = position

    pre = f"""
    main:
        %par = param
        %ptr_a = {a}
        %ptr_b = {b}
        %ptr_c = {c}
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload %ptr_a
        jmp @join
    else:
        %2 = mload %ptr_a
        jmp @join
    join:
        %3 = mload %ptr_b
        %cond_end = iszero %3
        jnz %cond_end, @end_a, @end_b
    end_a:
        %4 = mload %ptr_a
        sink %4
    end_b:
        %5 = mload %ptr_c
        sink %5
    """

    post = f"""
    main:
        %par = param
        %ptr_a = {a}
        %ptr_b = {b}
        %ptr_c = {c}
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        %1 = mload %ptr_a
        jmp @join
    else:
        %2 = mload %ptr_a
        jmp @join
    join:
        %6 = phi @then, %1, @else, %2
        %3 = mload %ptr_b
        %cond_end = iszero %3
        jnz %cond_end, @end_a, @end_b
    end_a:
        %4 = %6
        sink %4
    end_b:
        %5 = mload %ptr_c
        sink %5
    """

    _check_pre_post(pre, post)
