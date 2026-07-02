from tests.venom_utils import parse_from_basic_block
from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import BasePtrAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
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
