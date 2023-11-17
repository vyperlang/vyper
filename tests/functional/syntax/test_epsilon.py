import pytest

from vyper.exceptions import InvalidType

fail_list = [
    """
FOO: constant(address) = epsilon(address)
    """
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), InvalidType)
