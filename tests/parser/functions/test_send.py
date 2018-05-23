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
