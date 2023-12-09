from vyper.compiler.settings import Settings, OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.basicblock import IRLiteral
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

    op = ctx.append_instruction("store", [IRLiteral(10)])
    sum = ctx.append_instruction("add", [op, op])
    ctx.append_instruction("mul", [sum, op])
    ctx.append_instruction("stop", [], False)

    asm = generate_assembly_experimental(ctx, Settings(optimize=OptimizationLevel.CODESIZE))

    assert asm == ["PUSH1", 10, "DUP1", "DUP1", "DUP1", "ADD", "MUL", "STOP", "REVERT"]
