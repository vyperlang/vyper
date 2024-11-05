from vyper.evm.opcodes import version_check
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes import SCCP, MemMergePass


def test_memmerging():
    if version_check(end="shanghai"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    addr0 = bb.append_instruction("store", 0)
    addr1 = bb.append_instruction("store", 32)
    addr2 = bb.append_instruction("store", 64)
    oaddr0 = bb.append_instruction("store", 96)
    oaddr1 = bb.append_instruction("store", 128)
    oaddr2 = bb.append_instruction("store", 160)
    val0 = bb.append_instruction("mload", addr0)
    val1 = bb.append_instruction("mload", addr1)
    val2 = bb.append_instruction("mload", addr2)
    bb.append_instruction("mstore", val0, oaddr0)
    bb.append_instruction("mstore", val1, oaddr1)
    bb.append_instruction("mstore", val2, oaddr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mstore" for inst in bb.instructions)
    assert not any(inst.opcode == "mload" for inst in bb.instructions)
    assert not any(inst.opcode == "mload" for inst in bb.instructions)
    assert bb.instructions[6].opcode == "mcopy"
