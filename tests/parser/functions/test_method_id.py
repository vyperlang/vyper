import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation


def test_method_id_test():
    method_id_test = """
@public
def double(x: num) -> num:
    return x * 2

@public
def returnten() -> num:
    ans = raw_call(self, concat(method_id("double(int128)"), as_bytes32(5)), gas=50000, outsize=32)
    return as_num128(extract32(ans, 0))
    """
    c = get_contract_with_gas_estimation(method_id_test)
    assert c.returnten() == 10
    print("Passed method ID test")
