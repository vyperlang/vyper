
def test_throw_on_sending(w3, assert_tx_failed, get_contract_with_gas_estimation):
    code = """
x: public(int128)

@public
def __init__():
    self.x = 123
    """

    c = get_contract_with_gas_estimation(code)

    assert c.x() == 123

    assert w3.eth.getBalance(c.address) == 0
    assert_tx_failed(lambda: w3.eth.sendTransaction({'to': c.address, 'value': 10**17}))
    assert w3.eth.getBalance(c.address) == 0
