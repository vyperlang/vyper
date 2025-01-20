import pytest

from vyper.utils import evm_not
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLiteral
from vyper.venom.context import IRContext
from vyper.venom.passes import ReduceLiteralsCodesize


def _calc_push_size(val: int):
    s = hex(val).removeprefix("0x")
    if len(s) % 2 != 0:  # justify to multiple of 2
        s = "0" + s
    return 1 + len(s)


should_invert = [2**256 - 1] + [((2**i) - 1) << (256 - i) for i in range(121, 256 + 1)]


@pytest.mark.parametrize("orig_value", should_invert)
def test_literal_codesize_ff_inversion(orig_value):
    """
    Test that literals like 0xfffffffffffabcd get inverted to `not 0x5432`
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    inst0 = bb.instructions[0]
    assert inst0.opcode == "not"
    op0 = inst0.operands[0]
    assert evm_not(op0.value) == orig_value
    # check the optimization actually improved codesize, after accounting
    # for the addl NOT instruction
    assert _calc_push_size(op0.value) + 1 < _calc_push_size(orig_value)


should_not_invert = [1, 0xFE << 248 | (2**248 - 1)] + [
    ((2**255 - 1) >> i) << i for i in range(0, 3 * 8)
]


@pytest.mark.parametrize("orig_value", should_not_invert)
def test_literal_codesize_no_inversion(orig_value):
    """
    Check funky cases where inversion would result in bytecode increase
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "store"
    assert bb.instructions[0].operands[0].value == orig_value


should_shl = (
    [2**i for i in range(3 * 8, 255)]
    + [((2**i) - 1) << (256 - i) for i in range(1, 121)]
    + [((2**255 - 1) >> i) << i for i in range(3 * 8, 254)]
)


@pytest.mark.parametrize("orig_value", should_shl)
def test_literal_codesize_shl(orig_value):
    """
    Test that literals like 0xabcd00000000 get transformed to `shl 32 0xabcd`
    """
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

    # check the optimization actually improved codesize, after accounting
    # for the addl PUSH and SHL instructions
    assert _calc_push_size(op0.value) + _calc_push_size(op1.value) + 1 < _calc_push_size(orig_value)


should_not_shl = [1 << i for i in range(0, 3 * 8)] + [
    0x0,
    (((2 ** (256 - 2)) - 1) << (2 * 8)) ^ (2**255),
]


@pytest.mark.parametrize("orig_value", should_not_shl)
def test_literal_codesize_no_shl(orig_value):
    """
    Check funky cases where shl transformation would result in bytecode increase
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")
    bb = fn.get_basic_block()

    bb.append_instruction("store", IRLiteral(orig_value))
    bb.append_instruction("stop")
    ac = IRAnalysesCache(fn)
    ReduceLiteralsCodesize(ac, fn).run_pass()

    assert bb.instructions[0].opcode == "store"
    assert bb.instructions[0].operands[0].value == orig_value
