import pytest

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
def foo(b: decimal):
    y: decimal = min(-1, 18707220957835557353007165858768422651595.9365500928)
    """,
        OverflowException,
        # right value is out of bounds, caught by validation of literal nodes
    ),
    (
        """
@external
def foo():
    y: int256 = min(-1, 57896044618658097711785492504343953926634992332820282019728792003956564819967)  # noqa: E501
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exception", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exception):

    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exception)
