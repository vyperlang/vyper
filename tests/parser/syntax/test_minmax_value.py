import pytest

from vyper.exceptions import InvalidType

fail_list = [
    """
@external
def foo():
    a: address = min_value(address)
    """,
    """
@external
def foo():
    a: address = max_value(address)
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), InvalidType)
