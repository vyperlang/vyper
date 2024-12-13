import pytest

from vyper.evm.opcodes import version_check
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes import SCCP, MemMergePass, RemoveUnusedVariablesPass


def _nochange(instructions, bb):
    if len(instructions) != len(bb.instructions):
        return False
    return all(inst1 is inst2 for (inst1, inst2) in zip(instructions, bb.instructions))


def test_memmerging():
    """
    Basic memory merge test
    All mloads and mstores can be
    transformed into mcopy
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 0)
    val1 = bb.append_instruction("mload", 32)
    val2 = bb.append_instruction("mload", 64)
    bb.append_instruction("mstore", val0, 1024)
    bb.append_instruction("mstore", val1, 1024 + 32)
    bb.append_instruction("mstore", val2, 1024 + 64)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mstore" for inst in bb.instructions)
    assert not any(inst.opcode == "mload" for inst in bb.instructions), bb
    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 96
    assert bb.instructions[0].operands[1].value == 0
    assert bb.instructions[0].operands[2].value == 1024


def test_memmerging_out_of_order():
    """
    Test with out of order memory
    operations which all can be
    transformed into the mcopy
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val1 = bb.append_instruction("mload", 32)
    val0 = bb.append_instruction("mload", 0)
    bb.append_instruction("mstore", val1, 128)
    val2 = bb.append_instruction("mload", 64)
    bb.append_instruction("mstore", val2, 160)
    bb.append_instruction("mstore", val0, 96)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mstore" for inst in bb.instructions)
    assert not any(inst.opcode == "mload" for inst in bb.instructions)
    assert bb.instructions[0].opcode == "mcopy"


def test_memmerging_imposs():
    """
    Test case of impossible merge
    Impossible because of the overlap
    [64        160]
          [96        192]
    """
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


def test_memmerging_imposs_mstore():
    """
    Test case of impossible merge
    Impossible because of the mstore barrier
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 0)
    val1 = bb.append_instruction("mload", 16)
    bb.append_instruction("mstore", val0, 1024)
    val2 = bb.append_instruction("mload", 1024)
    bb.append_instruction("mstore", val1, 1024 + 16)
    bb.append_instruction("mstore", val2, 2048)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mcopy" for inst in bb.instructions)


@pytest.mark.xfail
def test_memmerging_bypass_fence():
    """
    We should be able to optimize this to an mcopy(0, 1024, 64), but
    currently do not
    """
    if not version_check(begin="cancun"):
        raise AssertionError()  # xfail
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 0)
    val1 = bb.append_instruction("mload", 32)
    bb.append_instruction("mstore", val0, 1024)
    val2 = bb.append_instruction("mload", 1024)
    bb.append_instruction("mstore", val1, 1024 + 32)
    bb.append_instruction("mstore", val2, 2048)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"


def test_memmerging_imposs_unkown_place():
    """
    Test case of impossible merge
    Impossible because of the
    non constant address mload and mstore barier
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    par = bb.append_instruction("param")
    val0 = bb.append_instruction("mload", 0)
    unknown_place = bb.append_instruction("mload", par)
    val1 = bb.append_instruction("mload", 32)
    val2 = bb.append_instruction("mload", 64)
    bb.append_instruction("mstore", val0, 96)
    bb.append_instruction("mstore", val1, 128)
    bb.append_instruction("mstore", 10, par)
    bb.append_instruction("mstore", val2, 160)
    bb.append_instruction("mstore", unknown_place, 1024)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert not any(inst.opcode == "mcopy" for inst in bb.instructions)


def test_memmerging_imposs_msize():
    """
    Test case of impossible merge
    Impossible because of the msize barier
    """
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
    """
    Only partial merge possible
    because of the msize barier
    """
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

    assert bb.instructions[-2].opcode == "mstore"
    assert bb.instructions[-3].opcode == "msize"
    assert bb.instructions[-4].opcode == "mcopy"
    assert bb.instructions[-4].operands[0].value == 64
    assert bb.instructions[-5].opcode == "mload"


def test_memmerging_partial_overlap():
    """
    Only partial merge possible
    because of the source overlap

    [0                     128]
        [24    88]
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    val0 = bb.append_instruction("mload", 0)
    val1 = bb.append_instruction("mload", 32)
    val2 = bb.append_instruction("mload", 64)
    val3 = bb.append_instruction("mload", 96)
    val4 = bb.append_instruction("mload", 24)
    val5 = bb.append_instruction("mload", 24 + 32)

    bb.append_instruction("mstore", val2, 1024 + 64)
    bb.append_instruction("mstore", val3, 1024 + 96)
    bb.append_instruction("mstore", val0, 1024)
    bb.append_instruction("mstore", val1, 1024 + 32)
    bb.append_instruction("mstore", val4, 2048 + 24)
    bb.append_instruction("mstore", val5, 2048 + 24 + 32)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 128
    assert bb.instructions[0].operands[1].value == 0
    assert bb.instructions[0].operands[2].value == 1024
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[1].value == 24
    assert bb.instructions[1].operands[2].value == 2048 + 24


def test_memmerging_partial_different_effect():
    """
    Only partial merge possible
    because of the generic memory
    effect barier
    """
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
    bb.append_instruction("dloadbytes", 1024, 1024, 2048)
    bb.append_instruction("mstore", val2, oaddr2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SCCP(ac, fn).run_pass()
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[-2].opcode == "mstore"
    assert bb.instructions[-3].opcode == "dloadbytes"
    assert bb.instructions[-4].opcode == "mcopy"
    assert bb.instructions[-4].operands[0].value == 64
    assert bb.instructions[-5].opcode == "mload"


def test_memmerging_ok_overlap():
    """
    Test for with source overlap
    which is ok to do
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 32)
    val1 = bb.append_instruction("mload", 32 + 24)
    val2 = bb.append_instruction("mload", 32 + 24 + 24)

    bb.append_instruction("mstore", val0, 1024)
    bb.append_instruction("mstore", val1, 1024 + 24)
    bb.append_instruction("mstore", val2, 1024 + 24 + 24)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 32 + 24 + 24
    assert bb.instructions[0].operands[1].value == 32
    assert bb.instructions[0].operands[2].value == 1024


def test_memmerging_mcopy():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mcopy", 32, 0, 1024)
    bb.append_instruction("mcopy", 32, 32, 1024 + 32)
    bb.append_instruction("mcopy", 64, 64, 1024 + 64)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 128
    assert bb.instructions[0].operands[1].value == 0
    assert bb.instructions[0].operands[2].value == 1024


def test_memmerging_mcopy_small():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mcopy", 16, 0, 1024)
    bb.append_instruction("mcopy", 16, 16, 1024 + 16)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 0
    assert bb.instructions[1].opcode == "mstore"
    assert bb.instructions[1].operands[0] == bb.instructions[0].output
    assert bb.instructions[1].operands[1].value == 1024


def test_memmerging_mcopy_weird_bisect():
    """
    Check that bisect_left finds the correct merge
    copy(80, 100, 2)
    copy(150, 60, 1)
    copy(82, 102, 3)
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("mcopy", 2, 100, 80)
    bb.append_instruction("mcopy", 1, 60, 150)
    bb.append_instruction("mcopy", 3, 102, 82)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 1
    assert bb.instructions[0].operands[1].value == 60
    assert bb.instructions[0].operands[2].value == 150
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 5
    assert bb.instructions[1].operands[1].value == 100
    assert bb.instructions[1].operands[2].value == 80
    assert bb.instructions[2].opcode == "stop"


def test_memmerging_mcopy_weird_bisect2():
    """
    Check that bisect_left finds the correct merge
    copy(80, 50, 2)
    copy(20, 100, 1)
    copy(82, 52, 3)
    """
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("mcopy", 2, 50, 80)
    bb.append_instruction("mcopy", 1, 100, 20)
    bb.append_instruction("mcopy", 3, 52, 82)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 1
    assert bb.instructions[0].operands[1].value == 100
    assert bb.instructions[0].operands[2].value == 20
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 5
    assert bb.instructions[1].operands[1].value == 50
    assert bb.instructions[1].operands[2].value == 80
    assert bb.instructions[2].opcode == "stop"


def test_memmerging_allowed_overlapping():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 64)
    bb.append_instruction("mcopy", 128, 64, 1024)
    val1 = bb.append_instruction("mload", 32)
    bb.append_instruction("mstore", val0, 2048 + 32)
    bb.append_instruction("mstore", val1, 2048)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 128
    assert bb.instructions[0].operands[1].value == 64
    assert bb.instructions[0].operands[2].value == 1024
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[1].value == 32
    assert bb.instructions[1].operands[2].value == 2048


def test_memmerging_not_allowed_overlapping():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    val0 = bb.append_instruction("mload", 1024)
    val1 = bb.append_instruction("mload", 1024 + 32)
    bb.append_instruction("mcopy", 128, 64, 1024)
    bb.append_instruction("mstore", val0, 2048)
    bb.append_instruction("mstore", val1, 2048 + 32)
    bb.append_instruction("stop")

    pre = bb.instructions.copy()

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert _nochange(pre, bb)


def test_memmerging_unused_mload():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val1 = bb.append_instruction("mload", 100)
    val2 = bb.append_instruction("mload", 132)
    bb.append_instruction("mstore", val2, 64)
    val = bb.append_instruction("mload", 32)
    bb.append_instruction("mstore", val1, 32)
    bb.append_instruction("return", val, val)

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 32
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[1].value == 100
    assert bb.instructions[1].operands[2].value == 32
    assert bb.instructions[2].opcode == "return"


def test_memmerging_unused_mload_1():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val1 = bb.append_instruction("mload", 100)
    val2 = bb.append_instruction("mload", 132)
    bb.append_instruction("mstore", val1, 0)
    val = bb.append_instruction("mload", 32)
    bb.append_instruction("mstore", val2, 32)
    bb.append_instruction("return", val, val)

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 32
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[1].value == 100
    assert bb.instructions[1].operands[2].value == 0
    assert bb.instructions[2].opcode == "return"


def test_memmerging_mload_read_after_write_hazard():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val1 = bb.append_instruction("mload", 100)
    val2 = bb.append_instruction("mload", 132)
    bb.append_instruction("mstore", val1, 0)
    val3 = bb.append_instruction("mload", 32)
    bb.append_instruction("mstore", val2, 32)
    val4 = bb.append_instruction("mload", 64)
    bb.append_instruction("mstore", val3, 1024)
    bb.append_instruction("mstore", val4, 1024 + 32)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mload"
    assert bb.instructions[0].operands[0].value == 32
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[1].value == 100
    assert bb.instructions[1].operands[2].value == 0
    assert bb.instructions[2].opcode == "mload"
    assert bb.instructions[2].operands[0].value == 64
    assert bb.instructions[3].opcode == "mstore"
    assert bb.instructions[3].operands[0] == bb.instructions[0].output
    assert bb.instructions[3].operands[1].value == 1024
    assert bb.instructions[4].opcode == "mstore"
    assert bb.instructions[4].operands[0] == bb.instructions[2].output
    assert bb.instructions[4].operands[1].value == 1024 + 32
    assert bb.instructions[5].opcode == "stop"


def test_memmerging_mcopy_read_after_write_hazard():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mcopy", 64, 32, 1024)
    bb.append_instruction("mcopy", 64, 1024, 2048)
    bb.append_instruction("mcopy", 64, 32 + 64, 1024 + 64)
    bb.append_instruction("stop")

    pre = bb.instructions.copy()
    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert _nochange(pre, bb), bb


def test_memmerging_write_after_write():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    val00 = bb.append_instruction("mload", 0)
    val10 = bb.append_instruction("mload", 100)
    val01 = bb.append_instruction("mload", 32)
    val11 = bb.append_instruction("mload", 132)
    bb.append_instruction("mstore", val00, 1000)
    bb.append_instruction("mstore", val10, 1000)
    bb.append_instruction("mstore", val11, 1032)
    bb.append_instruction("mstore", val01, 1032)
    bb.append_instruction("stop")

    pre = bb.instructions.copy()
    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert _nochange(pre, bb), bb


def test_memmerging_write_after_write_mstore_and_mcopy():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    val0 = bb.append_instruction("mload", 0)
    val1 = bb.append_instruction("mload", 132)
    bb.append_instruction("mstore", val0, 1000)
    bb.append_instruction("mcopy", 16, 100, 1000)
    bb.append_instruction("mstore", val1, 1032)
    bb.append_instruction("mcopy", 64, 116, 1016)
    bb.append_instruction("stop")

    pre = bb.instructions.copy()
    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert _nochange(pre, bb), bb


def test_memmerging_write_after_write_only_mcopy():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("mcopy", 16, 0, 1000)
    bb.append_instruction("mcopy", 16, 100, 1000)
    bb.append_instruction("mcopy", 64, 116, 1016)
    bb.append_instruction("mcopy", 64, 16, 1016)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mcopy"
    assert bb.instructions[0].operands[0].value == 16
    assert bb.instructions[0].operands[1].value == 0
    assert bb.instructions[0].operands[2].value == 1000
    assert bb.instructions[1].opcode == "mcopy"
    assert bb.instructions[1].operands[0].value == 16 + 64
    assert bb.instructions[1].operands[1].value == 100
    assert bb.instructions[1].operands[2].value == 1000
    assert bb.instructions[2].opcode == "mcopy"
    assert bb.instructions[2].operands[0].value == 64
    assert bb.instructions[2].operands[1].value == 16
    assert bb.instructions[2].operands[2].value == 1016


def test_memmerging_not_allowed_overlapping2():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("mload", 1024)
    val1 = bb.append_instruction("mload", 1024 + 32)
    bb.append_instruction("mcopy", 128, 64, 1024)  # src 128 dst 1024
    bb.append_instruction("mstore", val0, 2048)  # dst 2048
    bb.append_instruction("mstore", val1, 2048 + 32)
    bb.append_instruction("stop")

    pre = bb.instructions.copy()

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert _nochange(pre, bb)


def test_memmerging_existing_copy_overwrite():
    if not version_check(begin="cancun"):
        return
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mcopy", 64, 64, 1024)
    val = bb.append_instruction("mload", 2048)
    bb.append_instruction("mstore", val, 64)
    bb.append_instruction("mcopy", 64, 64 + 64, 1024 + 64)
    bb.append_instruction("stop")

    orig = bb.instructions.copy()
    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert orig == bb.instructions


def test_memmerging_calldataload():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("calldataload", 32)
    bb.append_instruction("mstore", val0, 64)
    val1 = bb.append_instruction("calldataload", 64)
    bb.append_instruction("mstore", val1, 64 + 32)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatacopy"
    assert bb.instructions[0].operands[0].value == 64
    assert bb.instructions[0].operands[1].value == 32
    assert bb.instructions[0].operands[2].value == 64


def test_memmerging_calldataload_two_intervals_diff_offset():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    val0 = bb.append_instruction("calldataload", 32)
    bb.append_instruction("mstore", val0, 64)
    bb.append_instruction("calldatacopy", 64, 32 + 32, 64 + 32)
    val1 = bb.append_instruction("calldataload", 32)
    bb.append_instruction("mstore", val1, 64 + 8)
    bb.append_instruction("calldatacopy", 64, 32 + 32, 64 + 32 + 8)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatacopy"
    assert bb.instructions[0].operands[0].value == 32 + 64
    assert bb.instructions[0].operands[1].value == 32
    assert bb.instructions[0].operands[2].value == 64
    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 32 + 64
    assert bb.instructions[1].operands[1].value == 32
    assert bb.instructions[1].operands[2].value == 64 + 8


def test_memzeroing_1():
    """
    Test of basic memzeroing
    done with mstore only
    """
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
    """
    Test of basic memzeroing
    done with calldatacopy only

    sequence of these instruction will
    zero out the memory at destination
    %1 = calldatasize
    calldatacopy <dst> %1 <size>
    """
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
    """
    Test of basic memzeroing
    done with combination of
    mstores and calldatacopies
    """
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


def test_memzeroing_small_calldatacopy():
    """
    Test of converting calldatacopy of
    size 32 into the mstore
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 32, calldatasize, 64)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "mstore"
    assert bb.instructions[0].operands[0].value == 0
    assert bb.instructions[0].operands[1].value == 64


def test_memzeroing_smaller_calldatacopy():
    """
    Test of converting smaller (<32) calldatacopies
    into either calldatacopy or mstore
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 8, calldatasize, 64)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 16, calldatasize, 64 + 8)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 8, calldatasize, 128)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 16, calldatasize, 128 + 8)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 8, calldatasize, 128 + 8 + 16)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"

    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 24
    assert bb.instructions[1].operands[2].value == 64

    assert bb.instructions[2].opcode == "mstore"
    assert bb.instructions[2].operands[0].value == 0
    assert bb.instructions[2].operands[1].value == 128


def test_memzeroing_overlap():
    """
    Test of merging ovelaping zeroing intervals

    [128        160]
        [136                  192]
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    bb.append_instruction("mstore", 0, 128)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 32 + 24, calldatasize, 128 + 8)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"

    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 64
    assert bb.instructions[1].operands[2].value == 128
    assert bb.instructions[2].opcode == "stop"


def test_memzeroing_imposs():
    """
    Test of memzeroing bariers caused
    by non constant arguments
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    par = bb.append_instruction("param")
    bb.append_instruction("mstore", 0, 32)
    bb.append_instruction("mstore", 0, par)  # barier
    bb.append_instruction("mstore", 0, 64)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", par, calldatasize, 10)  # barier
    bb.append_instruction("mstore", 0, 96)
    calldatasize = bb.append_instruction("calldatasize")
    bb.append_instruction("calldatacopy", 10, calldatasize, par)  # barier
    bb.append_instruction("mstore", 0, 128)
    bb.append_instruction("calldatacopy", 10, par, 10)  # barier
    bb.append_instruction("mstore", 0, 160)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[1].opcode == "mstore"
    assert bb.instructions[2].opcode == "mstore"
    assert bb.instructions[3].opcode == "mstore"
    assert bb.instructions[4].opcode == "calldatasize"
    assert bb.instructions[5].opcode == "calldatacopy"
    assert bb.instructions[6].opcode == "mstore"
    assert bb.instructions[7].opcode == "calldatasize"
    assert bb.instructions[8].opcode == "calldatacopy"
    assert bb.instructions[9].opcode == "mstore"
    assert bb.instructions[10].opcode == "calldatacopy"
    assert bb.instructions[11].opcode == "mstore"
    assert bb.instructions[12].opcode == "stop"


def test_memzeroing_imposs_effect():
    """
    Test of memzeroing bariers caused
    by different effect
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mstore", 0, 32)
    bb.append_instruction("dloadbytes", 10, 20, 30)
    bb.append_instruction("mstore", 0, 64)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert not any(inst.opcode == "calldatacopy" for inst in bb.instructions)


def test_memzeroing_overlaping():
    """
    Test of memzeroing bariers caused
    by different effect
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    bb.append_instruction("mstore", 0, 32)
    bb.append_instruction("mstore", 0, 96)
    bb.append_instruction("mstore", 0, 32)
    bb.append_instruction("mstore", 0, 64)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MemMergePass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "calldatasize"
    assert bb.instructions[1].opcode == "calldatacopy"
    assert bb.instructions[1].operands[0].value == 128 - 32
    assert bb.instructions[1].operands[1] == bb.instructions[0].output
    assert bb.instructions[1].operands[2].value == 32