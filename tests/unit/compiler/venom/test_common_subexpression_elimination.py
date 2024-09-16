from vyper.venom.context import IRContext
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.extract_literals import ExtractLiteralsPass
from vyper.venom.analysis.analysis import IRAnalysesCache

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

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 1, "wrong number of adds"
    assert sum(1 for inst in bb.instructions if inst.opcode == "mul") == 1, "wrong number of muls"
