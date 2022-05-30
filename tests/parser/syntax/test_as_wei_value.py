import pytest

from vyper.exceptions import ArgumentException, InvalidType, StructureException

fail_list = [
    (
        """
@external
def foo():
    x: int128 = as_wei_value(5, szabo)
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
        InvalidType,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_as_wei_fail(get_contract_with_gas_estimation, bad_code, exc, assert_compile_failed):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)


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
]


@pytest.mark.parametrize("good_code", valid_list)
def test_as_wei_success(good_code, get_contract_with_gas_estimation):
    assert get_contract_with_gas_estimation(good_code) is not None
