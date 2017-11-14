import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation


def test_send():
    send_test = """

def foo():
    send(msg.sender, self.balance+1)

def fop():
    send(msg.sender, 10)
    """
    c = s.contract(send_test, language='viper', value=10)
    with pytest.raises(t.TransactionFailed):
        c.foo()
    c.fop()
    with pytest.raises(t.TransactionFailed):
        c.fop()
