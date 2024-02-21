import hypothesis
import pytest


@pytest.fixture(scope="module")
def little_endian_contract(get_contract_module):
    code = """
@internal
@view
def to_little_endian_64(_value: uint256) -> Bytes[8]:
    y: uint256 = 0
    x: uint256 = _value
    for _: uint256 in range(8):
        y = (y << 8) | (x & 255)
        x >>= 8
    return slice(convert(y, bytes32), 24, 8)

@external
@view
def get_count(counter: uint256) -> Bytes[24]:
    return self.to_little_endian_64(counter)
    """
    c = get_contract_module(code)
    return c


@pytest.mark.fuzzing
@hypothesis.given(value=hypothesis.strategies.integers(min_value=0, max_value=2**64))
def test_zero_pad_range(little_endian_contract, value):
    actual_bytes = value.to_bytes(8, byteorder="little")
    contract_bytes = little_endian_contract.get_count(value)
    assert contract_bytes == actual_bytes
