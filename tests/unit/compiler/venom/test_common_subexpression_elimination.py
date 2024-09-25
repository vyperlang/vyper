import pytest

from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.analysis.available_expression import AvailableExpressionAnalysis
from vyper.venom.context import IRContext
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.extract_literals import ExtractLiteralsPass


def test_common_subexpression_elimination():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    sum_1 = bb.append_instruction("add", op, 10)
    bb.append_instruction("mul", sum_1, 10)
    sum_2 = bb.append_instruction("add", op, 10)
    bb.append_instruction("mul", sum_2, 10)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    CSE(ac, fn).run_pass()
    ExtractLiteralsPass(ac, fn).run_pass()
    print(fn)

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 1, "wrong number of adds"
    assert sum(1 for inst in bb.instructions if inst.opcode == "mul") == 1, "wrong number of muls"


def test_common_subexpression_elimination_effects_1():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    mload_1 = bb.append_instruction("mload", 0)
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_2 = bb.append_instruction("mload", 0)
    bb.append_instruction("add", mload_1, 10)
    bb.append_instruction("add", mload_2, 10)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    print(fn)

    avail: AvailableExpressionAnalysis = ac.force_analysis(AvailableExpressionAnalysis)

    for inst in bb.instructions:
        print(inst, avail.get_available(inst))

    DFTPass(ac, fn).run_pass()
    CSE(ac, fn).run_pass()
    ExtractLiteralsPass(ac, fn).run_pass()
    print(fn)

    avail: AvailableExpressionAnalysis = ac.force_analysis(AvailableExpressionAnalysis)

    for inst in bb.instructions:
        print(inst, avail.get_available(inst))

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 2, "wrong number of adds"


# This is a limitation of current implementation
@pytest.mark.xfail
def test_common_subexpression_elimination_effects_2():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    mload_1 = bb.append_instruction("mload", 0)
    bb.append_instruction("add", mload_1, 10)
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_2 = bb.append_instruction("mload", 0)
    bb.append_instruction("add", mload_1, 10)
    bb.append_instruction("add", mload_2, 10)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    DFTPass(ac, fn).run_pass()
    CSE(ac, fn).run_pass()
    ExtractLiteralsPass(ac, fn).run_pass()
    print(fn)

    avail: AvailableExpressionAnalysis = ac.force_analysis(AvailableExpressionAnalysis)

    for inst in bb.instructions:
        print(inst, avail.get_available(inst))

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 2, "wrong number of adds"
