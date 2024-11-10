import pytest

from vyper.utils import evm_not
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.passes import ReduceLiteralsCodesize


@pytest.mark.parametrize("orig_value", [0xFF << 248, 2**256 - 1])
def test_ff_inversion(orig_value):
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "not"
    assert evm_not(bb.instructions[0].operands[0].value) == orig_value
