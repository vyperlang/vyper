import pytest

from vyper.exceptions import (
    StructureException
)
from eth_tester.exceptions import (
    TransactionFailed
)


def test_assert_refund(w3, get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@public
def foo():
    assert 1 == 2
"""
    c = get_contract_with_gas_estimation(code)
    a0 = w3.eth.accounts[0]
    pre_balance = w3.eth.getBalance(a0)
    # assert_tx_failed(lambda: c.foo(transact={'from': a0, 'gas': 10**6, 'gasPrice': 10}))
    assert_tx_failed(lambda: c.foo())
    post_balance = w3.eth.getBalance(a0)
    # Checks for gas refund from revert
    # 10**5 is added to account for gas used before the transactions fails
    assert pre_balance < post_balance + 10**5


def test_assert_reason(w3, get_contract_with_gas_estimation, assert_tx_failed):
    code = """
@public
def test(a: int128) -> int128:
    assert a > 1, "larger than one please"
    return 1 + a

@public
def test2(a: int128, b: int128) -> int128:
    c: int128 = 11
    assert a > 1, "a is not large enough"
    assert b == 1, "b may only be 1"
    return a + b + c
    """
    c = get_contract_with_gas_estimation(code)

    assert c.test(2) == 3
    with pytest.raises(TransactionFailed) as e_info:
        c.test(0)

    assert e_info.value.args[0] == b'larger than one please'
    # a = 0, b = 1
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(0, 1)
    assert e_info.value.args[0] == b'a is not large enough'
    # a = 1, b = 0
    with pytest.raises(TransactionFailed) as e_info:
        c.test2(2, 2)
    assert e_info.value.args[0] == b'b may only be 1'
    # return correct value
    assert c.test2(5, 1) == 17


def test_assert_reason_empty(get_contract, assert_compile_failed):
    code = """
@public
def test(a: int128) -> int128:
    assert a > 1, ""
    return 1 + a
    """
    assert_compile_failed(lambda: get_contract(code), StructureException)
