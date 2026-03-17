from tests.venom_utils import PrePostChecker, parse_from_basic_block
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.passes import AssignElimination, ConcretizeMemLocPass, RemoveUnusedVariablesPass

_check_pre_post = PrePostChecker(
    [ConcretizeMemLocPass, AssignElimination, RemoveUnusedVariablesPass], default_hevm=False
)


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


def test_surviving_store_no_overlap():
    """
    Regression for the DSE-vs-concretize liveness mismatch bug.

    An alloca (scratch) has a store early on, then a full overwrite
    later followed by a read. The liveat analysis kills scratch's
    liveness at the full overwrite, so the early mstore is NOT in
    scratch's liveset (liveat ∩ used). Meanwhile, buf IS live at the
    mstore instruction.

    Without the fix, the allocator sees no conflict between scratch
    and buf at the mstore instruction, and places both at address 0.
    The mstore to scratch then clobbers buf's data at runtime.

    With _mark_store_locations_live, the mstore forces scratch into
    the liveset at that instruction, preventing the overlap.
    """
    pre = """
    main:
        %scratch = alloca 32
        %buf = alloca 32
        calldatacopy %buf, 0, 32
        mstore %scratch, 42
        %v1 = mload %buf
        calldatacopy %scratch, 100, 32
        %v2 = mload %scratch
        sink %v1, %v2
    """

    ctx = parse_from_basic_block(pre)
    fn = list(ctx.functions.values())[0]
    ac = IRAnalysesCache(fn)
    ConcretizeMemLocPass(ac, fn).run_pass()

    allocator = ctx.mem_allocator
    intervals = sorted((pos, alloca.alloca_size) for alloca, pos in allocator.allocated.items())

    # verify no two allocations overlap — without the fix both would
    # be at position 0, causing the mstore to clobber buf
    for i in range(len(intervals) - 1):
        pos_a, size_a = intervals[i]
        pos_b, _ = intervals[i + 1]
        assert pos_a + size_a <= pos_b, (
            f"allocations overlap: [{pos_a}, {pos_a + size_a}) "
            f"and [{pos_b}, {pos_b + intervals[i + 1][1]})"
        )


def test_surviving_store_no_overlap_large():
    """
    Same pattern as test_surviving_store_no_overlap but with larger
    (64-byte) allocations to exercise non-trivial interval arithmetic.
    """
    pre = """
    main:
        %scratch = alloca 64
        %buf = alloca 64
        calldatacopy %buf, 0, 64
        mstore %scratch, 99
        %v1 = mload %buf
        calldatacopy %scratch, 200, 64
        %v2 = mload %scratch
        sink %v1, %v2
    """

    ctx = parse_from_basic_block(pre)
    fn = list(ctx.functions.values())[0]
    ac = IRAnalysesCache(fn)
    ConcretizeMemLocPass(ac, fn).run_pass()

    allocator = ctx.mem_allocator
    intervals = sorted((pos, alloca.alloca_size) for alloca, pos in allocator.allocated.items())

    for i in range(len(intervals) - 1):
        pos_a, size_a = intervals[i]
        pos_b, _ = intervals[i + 1]
        assert pos_a + size_a <= pos_b


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
