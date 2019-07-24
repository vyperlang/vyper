from decimal import (
    ROUND_FLOOR,
    Decimal,
    getcontext,
)

from eth_tester.exceptions import (
    TransactionFailed,
)
import hypothesis
import pytest

from vyper.utils import (
    SizeLimits,
)


@pytest.fixture(scope='module')
def little_endian_contract(get_contract_module):
    code = """
@private
@constant
def to_little_endian_64(value: uint256) -> bytes[8]:
    y: uint256 = 0
    x: uint256 = value
    for _ in range(8):
        y = shift(y, 8)
        y = y + bitwise_and(x, 255)
        x = shift(x, -8)
    return slice(convert(y, bytes32), start=24, len=8)

@public
@constant
def get_count(counter: uint256) -> bytes[24]:
    return self.to_little_endian_64(counter)
    """
    c = get_contract_module(code)
    return c


@hypothesis.given(
    value=hypothesis.strategies.integers(
        min_value=0,
        max_value=2**64,
    )
)
@hypothesis.settings(
    deadline=400,
)
def test_zero_pad_range(little_endian_contract, value):
    actual_bytes = value.to_bytes(8, byteorder="little")
    contract_bytes = little_endian_contract.get_count(value)
    assert contract_bytes == actual_bytes
