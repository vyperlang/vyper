from vyper.evm.opcodes import version_check
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes import SCCP, MemMergePass, RemoveUnusedVariablesPass


def test_memmerging():
    if not version_check(begin="cancun"):
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


def test_memmerging_imposs():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    addr0 = bb.append_instruction("store", 64)
    addr1 = bb.append_instruction("store", 96)
    addr2 = bb.append_instruction("store", 128)
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

    assert not any(inst.opcode == "mcopy" for inst in bb.instructions)

def test_memmerging_imposs_msize():
    if not version_check(begin="cancun"):
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
    bb.append_instruction("msize")
    val1 = bb.append_instruction("mload", addr1)
    val2 = bb.append_instruction("mload", addr2)
    bb.append_instruction("mstore", val0, oaddr0)
    bb.append_instruction("mstore", val1, oaddr1)
    bb.append_instruction("msize")
    bb.append_instruction("mstore", val2, oaddr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mcopy" for inst in bb.instructions)

def test_memmerging_partial_msize():
    if not version_check(begin="cancun"):
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
    bb.append_instruction("msize")
    bb.append_instruction("mstore", val2, oaddr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()
    print(fn)

    assert bb.instructions[-2].opcode ==  "mstore"
    assert bb.instructions[-3].opcode ==  "msize"
    assert bb.instructions[-4].opcode ==  "mload"
    assert bb.instructions[-5].opcode ==  "mcopy"
    assert bb.instructions[-5].operands[0].value == 64
    

def test_memzeroing_1():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("mstore", 0, 32)
    bb.append_instruction("mstore", 0, 64)
    bb.append_instruction("mstore", 0, 96)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"
    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 96
    assert bb.instructions[1].operands[2].value == 32
    assert len(bb.instructions) == 3


def test_memzeroing_2():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 128, calldatasize, 64)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 128, calldatasize, 192)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"
    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 256
    assert bb.instructions[1].operands[2].value == 64
    assert len(bb.instructions) == 3


def test_memzeroing_3():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 128, calldatasize, 64)
    bb.append_instruction("mstore", 0, 192)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 128, calldatasize, 224)
    bb.append_instruction("mstore", 0, 128 + 224)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"
    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 256 + 2 * 32
    assert bb.instructions[1].operands[2].value == 64
    assert len(bb.instructions) == 3
