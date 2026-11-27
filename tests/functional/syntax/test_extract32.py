import pytest

from vyper import compiler
from vyper.exceptions import ArgumentException, InvalidType, TypeMismatch

fail_list = [
    (
        """
@external
def foo() -> uint256:
    return extract32(b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
    """,
        TypeMismatch,  # default return type is bytes32
    ),
    (
        """
@external
def foo(inp: address) -> int128:
    return extract32(inp, 0, output_type=int128)
    """,
        TypeMismatch,  # can't extract32 on an address
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> int128:
    b: int128 = 1
    return extract32(inp, b, output_type=int128)
    """,
        TypeMismatch,  # `start` must be an unsigned integer
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> int128:
    return extract32(inp, -1, output_type=int128)
    """,
        TypeMismatch,  # `start` cannot be negative
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> bool:
    return extract32(inp, 0, output_type=bool)
    """,
        InvalidType,  # output_type can't be bool
    ),
    (
        """
@external
def foo() -> bytes32:
    return extract32(b"abc", 0)
    """,
        ArgumentException,  # a 3-byte literal can never hold 32 bytes
    ),
    (
        """
@external
def foo(inp: Bytes[31]) -> bytes32:
    return extract32(inp, 0)
    """,
        ArgumentException,  # Bytes[31] can never hold 32 bytes
    ),
    (
        """
@external
def foo(inp: Bytes[32]) -> bytes32:
    return extract32(inp, 1)
    """,
        ArgumentException,  # start + 32 > 32
    ),
    (
        """
@external
def foo(inp: Bytes[100]) -> bytes32:
    return extract32(inp, 69)
    """,
        ArgumentException,  # start + 32 > 100
    ),
    (
        """
START: constant(uint256) = 69

@external
def foo(inp: Bytes[100]) -> bytes32:
    return extract32(inp, START)
    """,
        ArgumentException,  # start folds to 69, start + 32 > 100
    ),
    (
        """
x: Bytes[100]

@external
def foo() -> uint256:
    return extract32(self.x, 100, output_type=uint256)
    """,
        ArgumentException,  # start + 32 > 100, storage variant
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_extract32_fail(assert_compile_failed, get_contract, bad_code, exc):
    assert_compile_failed(lambda: get_contract(bad_code), exc)


valid_list = [
    """
@external
def foo() -> uint256:
    return extract32(
        b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc",
        0,
        output_type=uint256
    )
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, output_type=uint256)
    """,
    """
x: Bytes[100]
@external
def foo() -> uint256:
    self.x = b"cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, output_type=uint256)
""",
    """
@external
def foo(inp: Bytes[100]) -> bytes32:
    return extract32(inp, 68)
    """,
    """
@external
def foo(inp: Bytes[32]) -> bytes32:
    return extract32(inp, 0)
    """,
    """
@external
def foo(inp: Bytes[100], start: uint256) -> bytes32:
    return extract32(inp, start)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_extract32_success(get_contract, good_code):
    assert get_contract(good_code) is not None


def test_extract32_out_of_bounds_message():
    code = """
@external
def foo() -> bytes32:
    return extract32(b"abc", 0)
    """
    with pytest.raises(ArgumentException) as e:
        compiler.compile_code(code)
    assert e.value.message == "extract32 out of bounds for Bytes[3]"
    assert e.value.annotations[0].node_source_code == 'b"abc"'
