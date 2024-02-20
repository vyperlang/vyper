def test_name_registry(w3, get_contract, tx_failed):
    a0, a1 = w3.eth.accounts[:2]
    with open("examples/name_registry/name_registry.vy") as f:
        code = f.read()
    c = get_contract(code)
    c.register(b"jacques", a0, transact={})
    assert c.lookup(b"jacques") == a0
    with tx_failed():
        c.register(b"jacques", a1)
