from vyper.venom.analysis.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes.common_subexpression_elimination import CSE
from vyper.venom.passes.store_expansion import StoreExpansionPass


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

    CSE(ac, fn).run_pass(1, 5)

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 1, "wrong number of adds"
    assert sum(1 for inst in bb.instructions if inst.opcode == "mul") == 1, "wrong number of muls"


def test_common_subexpression_elimination_commutative():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    sum_1 = bb.append_instruction("add", 10, op)
    bb.append_instruction("mul", sum_1, 10)
    sum_2 = bb.append_instruction("add", op, 10)
    bb.append_instruction("mul", sum_2, 10)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    CSE(ac, fn).run_pass(1, 5)

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

    CSE(ac, fn).run_pass()

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 2, "wrong number of adds"


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
    CSE(ac, fn).run_pass()

    assert sum(1 for inst in bb.instructions if inst.opcode == "add") == 2, "wrong number of adds"


def test_common_subexpression_elimination_logs():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    num2 = bb.append_instruction("store", 10)
    num1 = bb.append_instruction("store", 20)
    num3 = bb.append_instruction("store", 20)
    bb.append_instruction("log", num1)
    bb.append_instruction("log", num2)
    bb.append_instruction("log", num1)
    bb.append_instruction("log", num3)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    CSE(ac, fn).run_pass()

    assert sum(1 for inst in bb.instructions if inst.opcode == "log") == 4, "wrong number of log"


def test_common_subexpression_elimination_effects_3():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    addr1 = bb.append_instruction("store", 10)
    addr2 = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", 0, addr1)
    bb.append_instruction("mstore", 2, addr2)
    bb.append_instruction("mstore", 0, addr1)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    CSE(ac, fn).run_pass()

    assert (
        sum(1 for inst in bb.instructions if inst.opcode == "mstore") == 3
    ), "wrong number of mstores"


def test_common_subexpression_elimination_effect_mstore():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_1 = bb.append_instruction("mload", 0)
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_2 = bb.append_instruction("mload", 0)
    bb.append_instruction("add", mload_1, mload_2)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    CSE(ac, fn).run_pass(1, 5)

    assert (
        sum(1 for inst in bb.instructions if inst.opcode == "mstore") == 1
    ), "wrong number of mstores"
    assert (
        sum(1 for inst in bb.instructions if inst.opcode == "mload") == 1
    ), "wrong number of mloads"


def test_common_subexpression_elimination_effect_mstore_with_msize():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_1 = bb.append_instruction("mload", 0)
    op = bb.append_instruction("store", 10)
    bb.append_instruction("mstore", op, 0)
    mload_2 = bb.append_instruction("mload", 0)
    msize_read = bb.append_instruction("msize")
    bb.append_instruction("add", mload_1, msize_read)
    bb.append_instruction("add", mload_2, msize_read)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    StoreExpansionPass(ac, fn).run_pass()
    CSE(ac, fn).run_pass(1, 5)

    assert (
        sum(1 for inst in bb.instructions if inst.opcode == "mstore") == 2
    ), "wrong number of mstores"
    assert (
        sum(1 for inst in bb.instructions if inst.opcode == "mload") == 2
    ), "wrong number of mloads"


def test_common_subexpression_elimination_different_branches():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    addr = bb.append_instruction("store", 10)
    rand_cond = bb.append_instruction("mload", addr)

    br1 = IRBasicBlock(IRLabel("br1"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("br2"), fn)
    fn.append_basic_block(br2)
    join_bb = IRBasicBlock(IRLabel("join_bb"), fn)
    fn.append_basic_block(join_bb)

    bb.append_instruction("jnz", rand_cond, br1.label, br2.label)

    def do_same(bb: IRBasicBlock, rand: int):
        a = bb.append_instruction("store", 10)
        b = bb.append_instruction("store", 20)
        c = bb.append_instruction("add", a, b)
        bb.append_instruction("mul", c, rand)

    do_same(br1, 1)
    br1.append_instruction("jmp", join_bb.label)
    do_same(br2, 2)
    br2.append_instruction("jmp", join_bb.label)
    do_same(join_bb, 3)
    join_bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)

    StoreExpansionPass(ac, fn).run_pass()
    CSE(ac, fn).run_pass(1, 5)

    assert sum(1 for inst in br1.instructions if inst.opcode == "add") == 1, "wrong number of adds"
    assert sum(1 for inst in br2.instructions if inst.opcode == "add") == 1, "wrong number of adds"
    assert (
        sum(1 for inst in join_bb.instructions if inst.opcode == "add") == 1
    ), "wrong number of adds"
