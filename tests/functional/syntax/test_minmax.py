import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, OverflowException, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    y: int128 = min(7, 0x1234567890123456789012345678901234567890)
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    a: int16 = min(min_value(int16), max_value(int8))
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
   a: decimal = min(1.0, 18707220957835557353007165858768422651595.9365500928)
    """,
        OverflowException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


valid_list = [
    """
FOO: constant(uint256) = 123
BAR: constant(uint256) = 456
BAZ: constant(uint256) = min(FOO, BAR)

@external
def foo():
    a: uint256 = BAZ
    """,
    """
FOO: constant(uint256) = 123
BAR: constant(uint256) = 456
BAZ: constant(uint256) = max(FOO, BAR)

@external
def foo():
    a: uint256 = BAZ
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
