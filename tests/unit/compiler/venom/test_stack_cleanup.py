from vyper.venom.context import IRContext
from vyper.venom import generate_assembly_experimental
from vyper.compiler.settings import OptimizationLevel


def test_cleanup_stack():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    bb.append_instruction("add", op, op)
    bb.append_instruction("ret")

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    assert asm == ["PUSH1", 10, "DUP1", "ADD", "POP", "JUMP"]
