from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes.common_subexpression_elimination import CSE
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

def test_common_subexpression_elimination_effects():
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
    CSE(ac, fn).run_pass()
    ExtractLiteralsPass(ac, fn).run_pass()
    print(fn)

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 2, "wrong number of adds"
    #assert False
    #assert sum(1 for inst in bb.instructions if inst.opcode == "mul") == 1, "wrong number of muls"

