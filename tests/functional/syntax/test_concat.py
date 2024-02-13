import pytest

from vyper import compiler
from vyper.exceptions import ArgumentException, TypeMismatch

fail_list = [
    (
        """
@external
def cat(i1: Bytes[10], i2: Bytes[30]) -> Bytes[40]:
    return concat(i1, i2, i1, i1)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def cat(i1: Bytes[10], i2: Bytes[30]) -> Bytes[40]:
    return concat(i1, 5)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def sandwich(inp: Bytes[100], inp2: bytes32) -> Bytes[163]:
    return concat(inp2, inp, inp2)
    """,
        TypeMismatch,
    ),
    (
        """
y: Bytes[10]

@external
def krazykonkat(z: Bytes[10]) -> Bytes[24]:
    x: Bytes[10] = b"cow"
    self.y = b"horse"
    return concat(x, b" ", self.y, b" ", z)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def cat_list(y: int128) -> Bytes[40]:
    x: int128[1] = [y]
    return concat("test", y)
    """,
        TypeMismatch,
    ),
    (
        """
@external
def large_output(a: String[33], b: String[33]) -> String[64]:
    c: String[64] = concat(a, b)
    return c
    """,
        TypeMismatch,
    ),
    (
        """
@external
def large_output(a: String[33], b: address) -> String[64]:
    c: String[64] = concat(a, b)
    return c
    """,
        TypeMismatch,
    ),
    (
        """
@external
def large_output(a: String[33]) -> String[33]:
    c: String[33] = concat(a)
    return c
    """,
        ArgumentException,
    ),
    (
        """
@external
def large_output(a: String[33], b: String[33], reverse=True) -> String[64]:
    c: String[64] = concat(a, b)
    return c
    """,
        ArgumentException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
@external
def cat(i1: Bytes[10], i2: Bytes[30]) -> Bytes[40]:
    return concat(i1, i2)
    """,
    """
@external
def cat(i1: Bytes[10], i2: Bytes[30]) -> Bytes[40]:
    return concat(i1, i1, i1, i1)
    """,
    """
@external
def cat(i1: Bytes[10], i2: Bytes[30]) -> Bytes[40]:
    return concat(i1, i1)
    """,
    """
@external
def sandwich(inp: Bytes[100], inp2: bytes32) -> Bytes[165]:
    return concat(inp2, inp, inp2)
    """,
    """
y: Bytes[10]

@external
def krazykonkat(z: Bytes[10]) -> Bytes[25]:
    x: Bytes[3] = b"cow"
    self.y = b"horse"
    return concat(x, b" ", self.y, b" ", z)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
