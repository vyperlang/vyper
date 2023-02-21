import pytest

from vyper.exceptions import InvalidType, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    a: address = min_value(address)
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    a: address = max_value(address)
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
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):

    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
