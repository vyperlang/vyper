import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_clamper_test_code():
    clamper_test_code = """
def foo(s: bytes <= 3) -> bytes <= 3:
    return s
    """

    c = get_contract(clamper_test_code, value=1)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    try:
        c.foo(b"cate")
        success = True
    except t.TransactionFailed:
        success = False
    assert not success

    print("Passed bytearray clamping test")
