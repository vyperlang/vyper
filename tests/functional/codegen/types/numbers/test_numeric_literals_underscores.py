from decimal import Decimal

import pytest

from tests.utils import decimal_to_int


@pytest.mark.parametrize(
    "literal", ["123_456", "1_000_000", "1_2_3_4_5_6", "1_000", "9_999_999_999_999_999"]
)
def test_decimal_literals_with_underscores(get_contract, literal):
    """Test that decimal literals with underscores return correct values"""
    expected = int(literal)

    code = f"""
@external
def foo() -> uint256:
    return {literal}
    """
    c = get_contract(code)
    assert c.foo() == expected


@pytest.mark.parametrize(
    "literal",
    [
        "0x1234_5678",
        "0xFF_FF_FF_FF",
        "0x1_2_3_4",
        "0xdead_beef",
        "0x00_00_00_01",
        "0x_1234_5678",  # underscore after prefix is valid
    ],
)
def test_hex_literals_with_underscores(get_contract, literal):
    """Test that hex literals with underscores return correct values"""
    expected = int(literal, 16)

    code = f"""
@external
def foo() -> uint256:
    return convert({literal}, uint256)
    """
    c = get_contract(code)
    assert c.foo() == expected


@pytest.mark.parametrize("literal", ["0b1010_1010", "0b1111_0000_1111_0000", "0b11111111_11111111"])
def test_binary_literals_with_underscores(get_contract, literal):
    """Test that binary literals with underscores return correct values"""
    # convert 0b representation to b''
    value = int(literal, 2)
    num_bits = len(literal.replace("0b", "").replace("_", ""))
    num_bytes = (num_bits + 7) // 8
    expected = value.to_bytes(num_bytes, "big")

    code = f"""
@external
def foo() -> Bytes[32]:
    return {literal}
    """
    c = get_contract(code)
    assert c.foo() == expected


@pytest.mark.parametrize("literal", ["0o123_456", "0o7_7_7", "0o1_234_567"])
def test_octal_literals_with_underscores(get_contract, literal):
    """Test that octal literals with underscores return correct values"""
    expected = int(literal, 8)

    code = f"""
@external
def foo() -> uint256:
    return {literal}
    """
    c = get_contract(code)
    assert c.foo() == expected


@pytest.mark.parametrize(
    "literal", ["123_456.789", "1_000.000_1", "0.000_000_1", "1.234_567e10", "1_234.567_8e-5"]
)
def test_float_literals_with_underscores(get_contract, literal):
    """Test that float literals with underscores return correct values"""
    expected = Decimal(literal)

    code = f"""
@external
def foo() -> decimal:
    return {literal}
    """
    c = get_contract(code)
    assert c.foo() == decimal_to_int(expected)
