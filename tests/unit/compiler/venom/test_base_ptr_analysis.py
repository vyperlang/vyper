import pytest

from tests.venom_utils import parse_from_basic_block
from vyper.evm.address_space import MEMORY, STORAGE, TRANSIENT
from vyper.venom.analysis import BasePtrAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.base_ptr_analysis import Ptr
from vyper.venom.basicblock import IRVariable
from vyper.venom.memory_location import Allocation, MemoryLocation


def test_base_ptr_basic():
    code = """
    main:
        %alloca1 = alloca 256
        %2 = add 32, %alloca1
        %random = mload 123
        %3 = add %random, %alloca1
        %4 = add 32, %2
        stop
    """

    ctx = parse_from_basic_block(code)

    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr_analysis = ac.request_analysis(BasePtrAnalysis)

    source = fn.entry.instructions[0]

    base_ptr_1 = base_ptr_analysis.ptr_from_op(IRVariable("%alloca1"))
    base_ptr_2 = base_ptr_analysis.ptr_from_op(IRVariable("%2"))
    base_ptr_3 = base_ptr_analysis.ptr_from_op(IRVariable("%3"))
    base_ptr_4 = base_ptr_analysis.ptr_from_op(IRVariable("%4"))

    assert base_ptr_1 is not None
    assert base_ptr_2 is not None
    assert base_ptr_3 is not None
    assert base_ptr_4 is not None

    assert base_ptr_1.base_alloca.inst is source
    assert base_ptr_2.base_alloca.inst is source
    assert base_ptr_3.base_alloca.inst is source
    assert base_ptr_4.base_alloca.inst is source
    assert base_ptr_1.offset == 0
    assert base_ptr_2.offset == 32
    assert base_ptr_3.offset is None
    assert base_ptr_4.offset == 64


def test_base_ptr_instruction_with_no_memory_ops():
    code = """
    _global:
        %1 = 42  # Simple assignment with no memory operations
        stop
    """

    ctx = parse_from_basic_block(code)

    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr_analysis = ac.request_analysis(BasePtrAnalysis)

    # Get the block and instruction
    bb = fn.get_basic_block("_global")
    assignment_inst = bb.instructions[0]  # %1 = 42

    # Verify that the instruction doesn't have memory operations
    assert base_ptr_analysis.get_read_location(assignment_inst, MEMORY) is MemoryLocation.EMPTY
    assert base_ptr_analysis.get_write_location(assignment_inst, MEMORY) is MemoryLocation.EMPTY


@pytest.mark.parametrize(
    "reassignment, expected",
    [
        ("", MemoryLocation(offset=64, size=32)),
        ("%ptr = 0", MemoryLocation(offset=None, size=32)),
        ("%size = 0", MemoryLocation(offset=64, size=None)),
    ],
)
def test_base_ptr_literal_assign_chains(reassignment, expected):
    # A later pre-SSA assignment must not determine the location of this
    # earlier copy, even when the redefined variable is behind an alias.
    ctx = parse_from_basic_block(f"""
    main:
        %ptr = 64
        %size = 32
        %ptr_alias = %ptr
        %size_alias = %size
        calldatacopy %ptr_alias, 0, %size_alias
        {reassignment}
        stop
    """)
    fn = next(ctx.get_functions())
    base_ptr = IRAnalysesCache(fn).request_analysis(BasePtrAnalysis)
    copy = next(inst for inst in fn.entry.instructions if inst.opcode == "calldatacopy")

    assert base_ptr.get_write_location(copy, MEMORY) == expected


@pytest.mark.parametrize("addr_space", [STORAGE, TRANSIENT])
@pytest.mark.parametrize("signed_slot", [-1, -(2**255)])
@pytest.mark.parametrize("use_assign_chain", [False, True])
def test_base_ptr_storage_slot_representations(addr_space, signed_slot, use_assign_chain):
    unsigned_slot = signed_slot + 2**256
    slot = "%alias" if use_assign_chain else str(signed_slot)
    ctx = parse_from_basic_block(f"""
    main:
        %slot = {signed_slot}
        %alias = %slot
        %x = {addr_space.load_op} {slot}
        {addr_space.store_op} {unsigned_slot}, 1
        %y = {addr_space.load_op} {unsigned_slot}
        {addr_space.store_op} {slot}, 2
        sink %x, %y
    """)
    fn = next(ctx.get_functions())
    base_ptr = IRAnalysesCache(fn).request_analysis(BasePtrAnalysis)
    expected = MemoryLocation(offset=unsigned_slot, size=1)

    for inst in fn.entry.instructions:
        if inst.opcode == addr_space.load_op:
            assert base_ptr.get_read_location(inst, addr_space) == expected
        elif inst.opcode == addr_space.store_op:
            assert base_ptr.get_write_location(inst, addr_space) == expected


@pytest.mark.parametrize(
    "assignments", ["%ptr = %ptr", "%ptr = %other\n%other = %ptr", "%ptr = 64\n%ptr = %ptr"]
)
def test_base_ptr_cyclic_assign_chain_is_unknown(assignments):
    ctx = parse_from_basic_block(f"""
    main:
        {assignments}
        %value = mload %ptr
        sink %value
    """)
    fn = next(ctx.get_functions())
    base_ptr = IRAnalysesCache(fn).request_analysis(BasePtrAnalysis)
    load = next(inst for inst in fn.entry.instructions if inst.opcode == "mload")

    assert base_ptr.get_read_location(load, MEMORY) == MemoryLocation(offset=None, size=32)


def test_base_ptr_loop_offsets_collapse_to_unknown():
    code = """
    main:
        %p = dalloca 32
        jmp @loop

    loop:
        %p = add 32, %p
        jmp @loop
    """

    ctx = parse_from_basic_block(code)

    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr_analysis = ac.request_analysis(BasePtrAnalysis)

    ptr = base_ptr_analysis.ptr_from_op(IRVariable("%p"))

    assert ptr is not None
    assert ptr.base_alloca.inst.opcode == "dalloca"
    assert ptr.offset is None


def test_aliases_of_allocation():
    code = """
    main:
        %p = alloca 64
        %a0 = add 0, %p
        %a32 = add 32, %p
        %v = mload %a0
        sink %v
    """

    ctx = parse_from_basic_block(code)
    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr = ac.request_analysis(BasePtrAnalysis)

    alloca = fn.entry.instructions[0]
    aliases = base_ptr.aliases_of_allocation(Allocation(alloca))

    assert aliases == {IRVariable("%p"), IRVariable("%a0"), IRVariable("%a32")}


def test_aliases_of_allocation_ambiguous_returns_none():
    # %x merges pointers into two different allocations, so it cannot be
    # attributed unambiguously to either one.
    code = """
    main:
        %p = alloca 64
        %q = alloca 64
        %cond = 1
        jnz %cond, @b1, @b2
    b1:
        %x1 = add 0, %p
        jmp @join
    b2:
        %x2 = add 0, %q
        jmp @join
    join:
        %x = phi @b1, %x1, @b2, %x2
        %v = mload %x
        sink %v
    """

    ctx = parse_from_basic_block(code)
    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr = ac.request_analysis(BasePtrAnalysis)

    alloca_p = fn.entry.instructions[0]
    assert base_ptr.aliases_of_allocation(Allocation(alloca_p)) is None


def test_aliases_of_allocation_reassigned_to_non_pointer_returns_none():
    for replacement in ("%p = 0", "%p = calldataload 0"):
        code = f"""
        main:
            %tmp = alloca 64
            %p = %tmp
            {replacement}
            %v = mload %p
            sink %v
        """

        ctx = parse_from_basic_block(code)
        fn = next(ctx.get_functions())
        ac = IRAnalysesCache(fn)
        base_ptr = ac.request_analysis(BasePtrAnalysis)

        alloca = fn.entry.instructions[0]
        assert base_ptr.aliases_of_allocation(Allocation(alloca)) is None


def test_base_ptr_phi_facts_reach_uses_past_unchanged_blocks():
    # the analysis walks one arm into `join` and everything below it before
    # it visits the other arm, so that arm's allocation reaches %x only on
    # a later visit of `join`. %y is two blocks further down, behind a
    # block with no pointer instructions, and must still see both
    # allocations.
    code = """
    main:
        %c = calldataload 0
        jnz %c, @then, @else
    then:
        %a = alloca 64
        jmp @join
    else:
        %b = alloca 64
        jmp @join
    join:
        %x = phi @then, %a, @else, %b
        jmp @mid
    mid:
        jmp @use
    use:
        %y = add 32, %x
        %v = mload %y
        sink %v
    """

    ctx = parse_from_basic_block(code)
    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr = ac.request_analysis(BasePtrAnalysis)

    alloca_a = fn.get_basic_block("then").instructions[0]
    alloca_b = fn.get_basic_block("else").instructions[0]
    expected = {Ptr(Allocation(alloca_a), 32), Ptr(Allocation(alloca_b), 32)}
    assert set(base_ptr.get_possible_ptrs(IRVariable("%y"))) == expected

    # a read through %y may touch either allocation, so it cannot be pinned
    # to one of them
    load = fn.get_basic_block("use").instructions[1]
    assert base_ptr.get_read_location(load, MEMORY) == MemoryLocation(offset=None, size=32)
