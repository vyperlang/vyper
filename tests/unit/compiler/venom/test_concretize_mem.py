from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AssignElimination, ConcretizeMemLocPass, Mem2Var, RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker([ConcretizeMemLocPass, RemoveUnusedVariablesPass], default_hevm=False)
_check_pre_post_mem2var = PrePostChecker([Mem2Var, AssignElimination], default_hevm=False)


def test_valid_overlap():
    """
    Test for case where two different memory location
    do not overlap in the liveness, both of them should be
    assign to the same address
    """

    pre = """
    main:
        %ptr1 = alloca 256
        %ptr2 = alloca 256
        calldatacopy %ptr1, 100, 256
        %1 = mload %ptr1
        calldatacopy %ptr2, 200, 32
        %2 = mload %ptr2
        calldatacopy %ptr1, 1000, 256
        %3 = mload %ptr1
        sink %1, %2, %3
    """
    post = """
    main:
        calldatacopy 0, 100, 256
        %1 = mload 0
        calldatacopy 0, 200, 32
        %2 = mload 0
        calldatacopy 0, 1000, 256
        %3 = mload 0
        sink %1, %2, %3
    """

    _check_pre_post(pre, post)


def test_venom_allocation():
    pre = """
    main:
        %ptr = alloca 256
        calldatacopy %ptr, 100, 256
        %1 = mload %ptr
        sink %1
    """


    post = """
    main:
        calldatacopy 0, 100, 256
        %1 = mload 0
        sink %1
    """
    _check_pre_post(pre, post)


def test_venom_allocation_branches():
    pre = """
    main:
        %ptr1 = alloca 0, 256
        %ptr2 = alloca 1, 128
        %cond = source
        jnz %cond, @then, @else
    then:
        calldatacopy %ptr1, 100, 256
        %1 = mload %ptr1
        sink %1
    else:
        calldatacopy %ptr2, 1000, 64
        %2 = mload %ptr2
        sink %2
    """

    post = """
    main:
        %cond = source
        jnz %cond, @then, @else
    then:
        calldatacopy 0, 100, 256
        %1 = mload 0
        sink %1
    else:
        calldatacopy 0, 1000, 64
        %2 = mload 0
        sink %2
    """

    _check_pre_post(pre, post)
