from vyper import compiler


def test_self_balance(w3, get_contract_with_gas_estimation):
    code = """
@external
@view
def get_balance() -> uint256:
    a: uint256 = self.balance
    return a

@external
@payable
def __default__():
    pass
    """
    opcodes = compiler.compile_code(code, output_formats=["opcodes"])["opcodes"]
    assert "SELFBALANCE" in opcodes

    c = get_contract_with_gas_estimation(code)
    w3.eth.send_transaction({"to": c.address, "value": 1337})

    assert c.get_balance() == 1337
