import pytest

from vyper.utils import evm_not
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.passes import ReduceLiteralsCodesize


@pytest.mark.parametrize("orig_value", [0xFFFF << 240, 2**256 - 1])
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


should_not_invert = [1, 0xFE << 248 | (2**248 - 1)]  # 0xfeff...ff


@pytest.mark.parametrize("orig_value", should_not_invert)
def test_no_inversion(orig_value):
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "store"
    assert bb.instructions[0].operands[0].value == orig_value


should_shl = [0x01_000000]  # saves 3 bytes


@pytest.mark.parametrize("orig_value", should_shl)
def test_shl(orig_value):
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "shl"
    op0, op1 = bb.instructions[0].operands
    assert op0.value << op1.value == orig_value


should_not_shl = [0x01_00]  # only saves 2 bytes


@pytest.mark.parametrize("orig_value", should_not_shl)
def test_no_shl(orig_value):
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "store"
    assert bb.instructions[0].operands[0].value == orig_value
