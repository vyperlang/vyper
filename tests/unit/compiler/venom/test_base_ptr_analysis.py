from tests.venom_utils import parse_from_basic_block
from vyper.evm.address_space import MEMORY
from vyper.venom.analysis import BasePtrAnalysis
from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRVariable
from vyper.venom.memory_location import MemoryLocation


def test_base_ptr_basic():
    code = """
    main:
        %alloca1 = alloca 1, 256
        %2 = gep 32, %alloca1
        %random = mload 123
        %3 = gep %random, %alloca1
        %4 = gep 32, %2
        stop
    """

    ctx = parse_from_basic_block(code)

    fn = next(ctx.get_functions())
    ac = IRAnalysesCache(fn)
    base_ptr_analysis = ac.request_analysis(BasePtrAnalysis)

    source = fn.entry.instructions[0]

    base_ptr_1 = base_ptr_analysis.base_ptr_from_op(IRVariable("%alloca1"))
    base_ptr_2 = base_ptr_analysis.base_ptr_from_op(IRVariable("%2"))
    base_ptr_3 = base_ptr_analysis.base_ptr_from_op(IRVariable("%3"))
    base_ptr_4 = base_ptr_analysis.base_ptr_from_op(IRVariable("%4"))

    assert base_ptr_1 is not None
    assert base_ptr_2 is not None
    assert base_ptr_3 is not None
    assert base_ptr_4 is not None

    assert base_ptr_1.source is source
    assert base_ptr_2.source is source
    assert base_ptr_3.source is source
    assert base_ptr_4.source is source
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
