def test_constant_address_balance(w3, get_contract_with_gas_estimation):
    code = """
a: constant(address) = 0x776Ba14735FF84789320718cf0aa43e91F7A8Ce1

@external
def foo() -> uint256:
    x: uint256 = a.balance
    return x
    """
    address = "0x776Ba14735FF84789320718cf0aa43e91F7A8Ce1"

    c = get_contract_with_gas_estimation(code)

    assert c.foo() == 0

    w3.eth.send_transaction({"to": address, "value": 1337})

    assert c.foo() == 1337
