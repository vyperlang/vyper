from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.parser import parse_venom
from vyper.venom.passes import DFTPass


def test_storage_write_after_write_dependency():
    """
    Test that DFT pass preserves write-after-write dependencies for storage.
    Without the fix, writes could be reordered relative to each other.
    """
    source = """
    function test {
        test:
            %x = param
            %y = param
            sstore 0, %x       ; first write
            sstore 1, %y       ; second write to different slot
            sstore 0, %y       ; third write overwrites first
            stop
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    sstore0_indices = []

    for i, inst in enumerate(instructions):
        if inst.opcode == "sstore" and inst.operands[1].value == 0:
            sstore0_indices.append(i)

    assert len(sstore0_indices) == 2
    assert sstore0_indices[0] < sstore0_indices[1], "Write order to same slot must be preserved"


def test_memory_write_after_write_dependency():
    """
    Test that DFT pass preserves write-after-write dependencies for memory.
    """
    source = """
    function test {
        test:
            %x = param
            %y = param
            mstore 0, %x       ; first write
            mstore 32, %y      ; second write to different location
            mstore 0, %y       ; third write overwrites first
            return 0, 32
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    mstore0_indices = []

    for i, inst in enumerate(instructions):
        if inst.opcode == "mstore" and inst.operands[1].value == 0:
            mstore0_indices.append(i)

    assert len(mstore0_indices) == 2
    assert mstore0_indices[0] < mstore0_indices[1], "Write order to same location must be preserved"


def test_transient_write_after_write_dependency():
    """
    Test that DFT pass preserves write-after-write dependencies for transient storage.
    """
    source = """
    function test {
        test:
            %x = param
            %y = param
            tstore 0, %x       ; first write
            tstore 1, %y       ; second write to different slot
            tstore 0, %y       ; third write overwrites first
            stop
    }
    """

    ctx = parse_venom(source)
    fn = ctx.get_function(IRLabel("test"))

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()

    bb = fn.get_basic_block("test")
    instructions = bb.instructions

    tstore0_indices = []

    for i, inst in enumerate(instructions):
        if inst.opcode == "tstore" and inst.operands[1].value == 0:
            tstore0_indices.append(i)

    assert len(tstore0_indices) == 2
    assert tstore0_indices[0] < tstore0_indices[1], "Write order to same slot must be preserved"
