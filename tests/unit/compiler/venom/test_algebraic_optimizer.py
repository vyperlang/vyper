import pytest

import vyper
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes import AlgebraicOptimizationPass, MakeSSA, RemoveUnusedVariablesPass


@pytest.mark.parametrize("iszero_count", range(5))
def test_simple_jump_case(iszero_count):
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    jnz_input = op3

    for _ in range(iszero_count):
        jnz_input = bb.append_instruction("iszero", jnz_input)

    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    iszeros = [inst for inst in bb.instructions if inst.opcode == "iszero"]
    removed_iszeros = iszero_count - len(iszeros)

    assert removed_iszeros % 2 == 0
    assert len(iszeros) == iszero_count % 2


@pytest.mark.parametrize("iszero_count", range(1, 5))
def test_simple_bool_cast_case(iszero_count):
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    jnz_input = op3

    for _ in range(iszero_count):
        jnz_input = bb.append_instruction("iszero", jnz_input)

    bb.append_instruction("mstore", jnz_input, p1)
    bb.append_instruction("jmp", br1.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    iszeros = [inst for inst in bb.instructions if inst.opcode == "iszero"]
    removed_iszeros = iszero_count - len(iszeros)

    assert removed_iszeros % 2 == 0
    assert len(iszeros) in [1, 2]
    assert len(iszeros) % 2 == iszero_count % 2


@pytest.mark.parametrize("interleave_point", range(1, 5))
def test_interleaved_case(interleave_point):
    iszeros_after_interleave_point = interleave_point // 2
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", p1)
    op2 = bb.append_instruction("store", 64)
    op3 = bb.append_instruction("add", op1, op2)
    op3_inv = bb.append_instruction("iszero", op3)
    jnz_input = op3_inv
    for _ in range(interleave_point):
        jnz_input = bb.append_instruction("iszero", jnz_input)
    bb.append_instruction("mstore", jnz_input, p1)
    for _ in range(iszeros_after_interleave_point):
        jnz_input = bb.append_instruction("iszero", jnz_input)
    bb.append_instruction("jnz", jnz_input, br1.label, br2.label)

    br1.append_instruction("add", op3, 10)
    br1.append_instruction("stop")
    br2.append_instruction("add", op3, p1)
    br2.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    assert bb.instructions[-1].opcode == "jnz"
    if (interleave_point + iszeros_after_interleave_point) % 2 == 0:
        assert bb.instructions[-1].operands[0] == op3_inv
    else:
        assert bb.instructions[-1].operands[0] == op3


def test_offsets():
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()

    br1 = IRBasicBlock(IRLabel("then"), fn)
    fn.append_basic_block(br1)
    br2 = IRBasicBlock(IRLabel("else"), fn)
    fn.append_basic_block(br2)

    p1 = bb.append_instruction("param")
    op1 = bb.append_instruction("store", 32)
    op2 = bb.append_instruction("add", 0, IRLabel("mem"))
    op3 = bb.append_instruction("store", 64)
    bb.append_instruction("dloadbytes", op1, op2, op3)
    op5 = bb.append_instruction("mload", op3)
    op6 = bb.append_instruction("iszero", op5)
    bb.append_instruction("jnz", op6, br1.label, br2.label)

    op01 = br1.append_instruction("store", 32)
    op02 = br1.append_instruction("add", 0, IRLabel("mem"))
    op03 = br1.append_instruction("store", 64)
    br1.append_instruction("dloadbytes", op01, op02, op03)
    op05 = br1.append_instruction("mload", op03)
    op06 = br1.append_instruction("iszero", op05)
    br1.append_instruction("return", p1, op06)

    op11 = br2.append_instruction("store", 32)
    op12 = br2.append_instruction("add", 0, IRLabel("mem"))
    op13 = br2.append_instruction("store", 64)
    br2.append_instruction("dloadbytes", op11, op12, op13)
    op15 = br2.append_instruction("mload", op13)
    op16 = br2.append_instruction("iszero", op15)
    br2.append_instruction("return", p1, op16)

    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    AlgebraicOptimizationPass(ac, fn).run_pass()
    RemoveUnusedVariablesPass(ac, fn).run_pass()

    offset_count = 0
    for bb in fn.get_basic_blocks():
        for instruction in bb.instructions:
            assert instruction.opcode != "add"
            if instruction.opcode == "offset":
                offset_count += 1

    assert offset_count == 3


# Test the case of https://github.com/vyperlang/vyper/issues/4288
def test_ssa_after_algebraic_optimization():
    code = """
@internal
def _do_math(x: uint256) -> uint256:
    value: uint256 = x
    result: uint256 = 0

    if (x >> 128 != 0):
        x >>= 128
    if (x >> 64 != 0):
        x >>= 64

    if 1 < value:
        result = 1

    return result

@external
def run() -> uint256:
    return self._do_math(10)
    """

    vyper.compile_code(code, output_formats=["bytecode"])
