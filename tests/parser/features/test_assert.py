

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
