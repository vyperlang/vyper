from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes import StoreExpansionPass
from vyper.venom.settings import VenomSettings


def test_duplicate_operands():
    """
    Test the duplicate operands code generation.
    The venom code:

    %1 = 10
    %2 = add %1, %1
    %3 = mul %1, %2
    stop

    Should compile to: [PUSH1, 10, DUP1, DUP2, ADD, MUL, POP, STOP]
    """
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("store", 10)
    sum_ = bb.append_instruction("add", op, op)
    bb.append_instruction("mul", sum_, op)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    StoreExpansionPass(ac, fn).run_pass()

    optimize = OptimizationLevel.GAS
    asm = generate_assembly_experimental(ctx, VenomSettings.from_optimization_level(optimize))
    assert asm == ["PUSH1", 10, "DUP1", "DUP2", "ADD", "MUL", "POP", "STOP"]
