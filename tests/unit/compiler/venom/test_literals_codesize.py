import pytest

from tests.venom_utils import PrePostChecker
from vyper.utils import evm_not
from vyper.venom.passes import ReduceLiteralsCodesize

pytestmark = pytest.mark.hevm


def _calc_push_size(val: int):
    s = hex(val).removeprefix("0x")
    if len(s) % 2 != 0:  # justify to multiple of 2
        s = "0" + s
    return 1 + len(s)


_check_pre_post = PrePostChecker([ReduceLiteralsCodesize])


def _check_no_change(pre):
    _check_pre_post(pre, pre, hevm=False)


should_invert = [2**256 - 1] + [((2**i) - 1) << (256 - i) for i in range(121, 256 + 1)]


@pytest.mark.parametrize("orig_value", should_invert)
def test_literal_codesize_ff_inversion(orig_value):
    """
    Test that literals like 0xfffffffffffabcd get inverted to `not 0x5432`
    """
    pre = f"""
    main:
        %1 = {orig_value}
        sink %1
    """

    not_val = evm_not(orig_value)

    post = f"""
    main:
        %1 = not {not_val}
        sink %1
    """

    _check_pre_post(pre, post)

    # check the optimization actually improved codesize, after accounting
    # for the addl NOT instruction
    assert _calc_push_size(not_val) + 1 < _calc_push_size(orig_value)


should_not_invert = [1, 0xFE << 248 | (2**248 - 1)] + [
    ((2**255 - 1) >> i) << i for i in range(0, 3 * 8)
]


@pytest.mark.parametrize("orig_value", should_not_invert)
def test_literal_codesize_no_inversion(orig_value):
    """
    Check funky cases where inversion would result in bytecode increase
    """

    pre = f"""
    main:
        %1 = {orig_value}
        sink %1
    """

    _check_no_change(pre)


should_shl = (
    [(2**i, i) for i in range(3 * 8, 255)]
    + [(((2**i) - 1) << (256 - i), (256 - i)) for i in range(1, 121)]
    + [(((2**255 - 1) >> i) << i, i) for i in range(3 * 8, 254)]
)


@pytest.mark.parametrize("orig_value,shift_amount", should_shl)
def test_literal_codesize_shl(orig_value, shift_amount):
    """
    Test that literals like 0xabcd00000000 get transformed to `shl 32 0xabcd`
    """
    pre = f"""
    main:
        %1 = {orig_value}
        sink %1
    """

    new_val = orig_value >> shift_amount

    assert orig_value == new_val << shift_amount, "bad test input"

    post = f"""
    main:
        %1 = shl {shift_amount}, {new_val}
        sink %1
    """

    _check_pre_post(pre, post)

    # check the optimization actually improved codesize, after accounting
    # for the addl PUSH and SHL instructions
    old_size = _calc_push_size(orig_value)
    new_size = _calc_push_size(new_val) + _calc_push_size(shift_amount) + 1
    assert new_size < old_size, orig_value


should_not_shl = [1 << i for i in range(0, 3 * 8)] + [
    0x0,
    (((2 ** (256 - 2)) - 1) << (2 * 8)) ^ (2**255),
]


@pytest.mark.parametrize("orig_value", should_not_shl)
def test_literal_codesize_no_shl(orig_value):
    """
    Check funky cases where shl transformation would result in bytecode increase
    """
    pre = f"""
    main:
        %1 = {orig_value}
        sink %1
    """

    _check_no_change(pre)
