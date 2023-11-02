from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral

from vyper.venom.function import IRFunction
from vyper.venom.ir import generate_assembly_experimental


def test_duplicate_operands():
    """
    Test the duplicate operands code generation.
    The venom code:

    %1 = 10
    %2 = add %1, %1
    stop

    Should compile to: [PUSH1, 10, DUP1, ADD, STOP]
    """
    ctx = IRFunction()

    op = ctx.append_instruction("store", [IRLiteral(10)])
    ctx.append_instruction("add", [op, op])
    ctx.append_instruction("stop", [])

    asm = generate_assembly_experimental(ctx)

    assert asm[:5] == ["PUSH1", 10, "DUP1", "ADD", "STOP"]
