import pytest

from vyper import compile_code
from vyper.exceptions import (
    ArgumentException,
    InvalidLiteral,
    OverflowException,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
)

# CMC 2023-12-31 these tests could probably go in builtins/folding/

fail_list = [
    (
        """
@external
def foo():
    x: uint256 = as_wei_value(5, szabo)
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def foo():
    x: uint256 = as_wei_value(5, "szaboo")
    """,
        ArgumentException,
    ),
    (
        """
@external
def foo() -> int128:
    x: int128 = 45
    return x.balance
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    x: int128 = as_wei_value(0xf5, "szabo")
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> uint256:
    return as_wei_value(
        115792089237316195423570985008687907853269984665640564039457584007913129639937,
        'milliether'
    )
    """,
        OverflowException,
    ),
    (
        """
@external
def foo():
    x: uint256 = as_wei_value(-1, "szabo")
    """,
        InvalidLiteral,
    ),
    (
        """
FOO: constant(uint256) = as_wei_value(5, szabo)
    """,
        UndeclaredDefinition,
    ),
    (
        """
FOO: constant(uint256) = as_wei_value(5, "szaboo")
    """,
        ArgumentException,
    ),
    (
        """
FOO: constant(uint256) = as_wei_value(-1, "szabo")
    """,
        InvalidLiteral,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_as_wei_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: uint256 = as_wei_value(5, "finney") + as_wei_value(2, "babbage") + as_wei_value(8, "shannon")  # noqa: E501
    """,
    """
@external
def foo():
    z: int128 = 2 + 3
    x: uint256 = as_wei_value(2 + 3, "finney")
    """,
    """
@external
def foo():
    x: uint256 = as_wei_value(5.182, "babbage")
    """,
    """
@external
def foo() -> uint256:
    x: address = 0x1234567890123456789012345678901234567890
    return x.balance
    """,
    """
y: constant(String[5]) = "szabo"
x: constant(uint256) = as_wei_value(5, y)

@external
def foo():
    a: uint256 = x
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_as_wei_success(good_code, get_contract_with_gas_estimation):
    assert get_contract_with_gas_estimation(good_code) is not None
