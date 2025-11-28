from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AssignElimination, ConcretizeMemLocPass, Mem2Var

_check_pre_post = PrePostChecker([ConcretizeMemLocPass], default_hevm=False)
_check_pre_post_mem2var = PrePostChecker([Mem2Var, AssignElimination], default_hevm=False)


def test_valid_overlap():
    """
    Test for case where two different memory location
    do not overlap in the liveness, both of them should be
    assign to the same address
    """

    pre = """
    main:
        calldatacopy {@3,256}, 100, 256
        %1 = mload {@3,256}
        calldatacopy {@4,32}, 200, 32
        %2 = mload {@4,32}
        calldatacopy {@3,256}, 1000, 256
        %3 = mload {@3,256}
        sink %1, %2, %3
    """
    post = """
    main:
        calldatacopy 64, 100, 256
        %1 = mload 64
        calldatacopy 64, 200, 32
        %2 = mload 64
        calldatacopy 64, 1000, 256
        %3 = mload 64
        sink %1, %2, %3
    """

    _check_pre_post(pre, post)


def test_venom_allocation():
    pre = """
    main:
        %ptr = alloca 0, {@3,256}
        calldatacopy %ptr, 100, 256
        %1 = mload %ptr
        sink %1
    """

    post1 = """
    main:
        calldatacopy {@3,256}, 100, 256
        %1 = mload {@3,256}
        sink %1
    """

    post2 = """
    main:
        calldatacopy 64, 100, 256
        %1 = mload 64
        sink %1
    """

    _check_pre_post_mem2var(pre, post1)
    _check_pre_post(post1, post2)


def test_venom_allocation_branches():
    pre = """
    main:
        %ptr1 = alloca 0, {@3,256}
        %ptr2 = alloca 1, {@4,128}
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

    post1 = """
    main:
        %cond = source
        jnz %cond, @then, @else
    then:
        calldatacopy {@3,256}, 100, 256
        %1 = mload {@3,256}
        sink %1
    else:
        calldatacopy {@4,128}, 1000, 64
        %2 = mload {@4,128}
        sink %2
    """

    post2 = """
    main:
        %cond = source
        jnz %cond, @then, @else
    then:
        calldatacopy 64, 100, 256
        %1 = mload 64
        sink %1
    else:
        calldatacopy 64, 1000, 64
        %2 = mload 64
        sink %2
    """

    _check_pre_post_mem2var(pre, post1)
    _check_pre_post(post1, post2)
