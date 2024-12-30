import pytest

from vyper.exceptions import ZeroDivisionException

BAD_CODE = [
    """
@external
def foo() -> uint256:
    return 2 / 0
    """,
    """
@external
def foo() -> int128:
    return -2 / 0
    """,
    """
@external
def foo() -> decimal:
    return 2.22 / 0.0
    """,
    """
@external
def foo(a: uint256) -> uint256:
    return a / 0
    """,
    """
@external
def foo(a: int128) -> int128:
    return a / 0
    """,
    """
@external
def foo(a: decimal) -> decimal:
    return a / 0.0
    """,
]


@pytest.mark.parametrize("code", BAD_CODE)
def test_divide_by_zero(code, assert_compile_failed, get_contract):
    assert_compile_failed(lambda: get_contract(code), ZeroDivisionException)
