from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.context import IRContext


def test_cleanup_stack():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    ret_val = bb.append_instruction("param")
    op = bb.append_instruction("store", 10)
    op2 = bb.append_instruction("store", op)
    bb.append_instruction("add", op, op2)
    bb.append_instruction("ret", ret_val)

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    assert asm == ["PUSH1", 10, "DUP1", "ADD", "POP", "JUMP"]
