def test_send(assert_tx_failed, get_contract):
    send_test = """
@public
def foo():
    send(msg.sender, self.balance + 1)

@public
def fop():
    send(msg.sender, 10)
    """
    c = get_contract(send_test, value=10)
    assert_tx_failed(lambda: c.foo(transact={}))
    c.fop(transact={})
    assert_tx_failed(lambda: c.fop(transact={}))


def test_payable_tx_fail(assert_tx_failed, get_contract, w3):
    code = """
@public
def pay_me() -> bool:
    return True
    """
    c = get_contract(code)
    assert_tx_failed(lambda: c.pay_me(transact={'value': w3.toWei(0.1, 'ether')}))
