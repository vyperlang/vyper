def test_send(assert_tx_failed, chain):
    send_test = """
@public
def foo():
    send(msg.sender, self.balance+1)

@public
def fop():
    send(msg.sender, 10)
    """
    c = chain.contract(send_test, language='viper', value=10)
    assert_tx_failed(lambda: c.foo())
    c.fop()
    assert_tx_failed(lambda: c.fop())
