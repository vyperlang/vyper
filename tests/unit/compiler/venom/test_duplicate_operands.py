from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.function import IRFunction


def test_duplicate_operands():
    """
    Test the duplicate operands code generation.
    The venom code:

    %1 = 10
    %2 = add %1, %1
    %3 = mul %1, %2
    stop

    Should compile to: [PUSH1, 10, DUP1, DUP1, DUP1, ADD, MUL, STOP]
    """
    ctx = IRFunction()
    bb = ctx.get_basic_block()
    op = bb.append_instruction("store", 10)
    sum_ = bb.append_instruction("add", op, op)
    bb.append_instruction("mul", sum_, op)
    bb.append_instruction("stop")

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)

    assert asm == ["PUSH1", 10, "DUP1", "DUP1", "DUP1", "ADD", "MUL", "STOP"]
