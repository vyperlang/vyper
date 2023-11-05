import pytest

from vyper.compiler import compile_code
from vyper.exceptions import InvalidLiteral, InvalidOperation, TypeMismatch
from vyper.utils import unsigned_to_signed

code = """
@external
def _bitwise_and(x: uint256, y: uint256) -> uint256:
    return x & y

@external
def _bitwise_or(x: uint256, y: uint256) -> uint256:
    return x | y

@external
def _bitwise_xor(x: uint256, y: uint256) -> uint256:
    return x ^ y

@external
def _bitwise_not(x: uint256) -> uint256:
    return ~x

@external
def _shl(x: uint256, y: uint256) -> uint256:
    return x << y

@external
def _shr(x: uint256, y: uint256) -> uint256:
    return x >> y
    """


def test_bitwise_opcodes():
    opcodes = compile_code(code, output_formats=["opcodes"])["opcodes"]
    assert "SHL" in opcodes
    assert "SHR" in opcodes


def test_test_bitwise(get_contract_with_gas_estimation):
    c = get_contract_with_gas_estimation(code)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    assert c._bitwise_and(x, y) == (x & y)
    assert c._bitwise_or(x, y) == (x | y)
    assert c._bitwise_xor(x, y) == (x ^ y)
    assert c._bitwise_not(x) == 2**256 - 1 - x

    for t in (x, y):
        for s in (0, 1, 3, 255, 256):
            assert c._shr(t, s) == t >> s
            assert c._shl(t, s) == (t << s) % (2**256)


def test_signed_shift(get_contract_with_gas_estimation):
    code = """
@external
def _sar(x: int256, y: uint256) -> int256:
    return x >> y

@external
def _shl(x: int256, y: uint256) -> int256:
    return x << y
    """
    c = get_contract_with_gas_estimation(code)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    cases = [x, y, -x, -y]

    for t in cases:
        for s in (0, 1, 3, 255, 256):
            assert c._sar(t, s) == t >> s
            assert c._shl(t, s) == unsigned_to_signed((t << s) % (2**256), 256)


def test_precedence(get_contract):
    code = """
@external
def foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a | b & c, (a | b) & c)

@external
def bar(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a | ~b & c, (a | ~b) & c)

@external
def baz(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a + 8 | ~b & c * 2, (a  + 8 | ~b) & c * 2)
    """
    c = get_contract(code)
    assert tuple(c.foo(1, 6, 14)) == (1 | 6 & 14, (1 | 6) & 14) == (7, 6)
    assert tuple(c.bar(1, 6, 14)) == (1 | ~6 & 14, (1 | ~6) & 14) == (9, 8)
    assert tuple(c.baz(1, 6, 14)) == (1 + 8 | ~6 & 14 * 2, (1 + 8 | ~6) & 14 * 2) == (25, 24)


def test_literals(get_contract):
    code = """
@external
def _shr(x: uint256) -> uint256:
    return x >> 3

@external
def _shl(x: uint256) -> uint256:
    return x << 3
    """

    c = get_contract(code)
    assert c._shr(80) == 10
    assert c._shl(80) == 640


fail_list = [
    (
        # cannot shift non-uint256/int256 argument
        """
@external
def foo(x: uint8, y: uint8) -> uint8:
    return x << y
    """,
        InvalidOperation,
    ),
    (
        # cannot shift non-uint256/int256 argument
        """
@external
def foo(x: int8, y: uint8) -> int8:
    return x << y
    """,
        InvalidOperation,
    ),
    (
        # cannot shift by non-uint bits
        """
@external
def foo(x: uint256, y: int128) -> uint256:
    return x << y
    """,
        TypeMismatch,
    ),
    (
        # cannot left shift by more than 256 bits
        """
@external
def foo() -> uint256:
    return 2 << 257
    """,
        InvalidLiteral,
    ),
    (
        # cannot shift by negative amount
        """
@external
def foo() -> uint256:
    return 2 << -1
    """,
        InvalidLiteral,
    ),
    (
        # cannot shift by negative amount
        """
@external
def foo() -> uint256:
    return 2 << -1
    """,
        InvalidLiteral,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_shift_fail(get_contract_with_gas_estimation, bad_code, exc, assert_compile_failed):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
