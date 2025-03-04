import pytest

import vyper
from tests.venom_utils import PrePostChecker
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.passes import AlgebraicOptimizationPass, MakeSSA, RemoveUnusedVariablesPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(AlgebraicOptimizationPass, RemoveUnusedVariablesPass)


@pytest.mark.parametrize("iszero_count", range(5))
def test_simple_jump_case(iszero_count):
    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    pre = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        jnz %cond{iszero_count}, @then, @else
    then:
        %4 = add 10, %3
        jmp @join
    else:
        %5 = add %3, %par
        jmp @join
    join:
        %6 = phi @then, %4, @else, %5
        sink %6
    """

    post_chain = "%cond1 = iszero %cond0" if iszero_count % 2 == 1 else ""

    post = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        jnz %cond{iszero_count % 2}, @then, @else
    then:
        %4 = add 10, %3
        jmp @join
    else:
        %5 = add %3, %par
        jmp @join
    join:
        %6 = phi @then, %4, @else, %5
        sink %6
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("iszero_count", range(1, 5))
def test_simple_bool_cast_case(iszero_count):
    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    pre = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        sink %cond{iszero_count}
    """

    post_chain = "%cond1 = iszero %cond0"
    if iszero_count % 2 == 0:
        post_chain = f"""
        %cond1 = iszero %cond0
        %cond2 = iszero %cond1
        """

    end_cond = 2 if iszero_count % 2 == 0 else 1

    post = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        sink %cond{end_cond}
    """

    _check_pre_post(pre, post)


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
    pre = """
    main:
        %par = param
        %1 = add @main, 0
        jnz %par, @then, @else
    then:
        %2 = add @main, 10
        jmp @join
    else:
        %3 = add @main, 20
        jmp @join
    join:
        %4 = phi @then, %2, @else, %3
        sink %1, %4
    """

    post = """
    main:
        %par = param
        %1 = offset @main, 0
        jnz %par, @then, @else
    then:
        %2 = offset @main, 10
        jmp @join
    else:
        %3 = offset @main, 20
        jmp @join
    join:
        %4 = phi @then, %2, @else, %3
        sink %1, %4
    """

    _check_pre_post(pre, post)


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
