from vyper import compiler


def test_self_balance(env, get_contract):
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

    c = get_contract(code)
    env.set_balance(env.deployer, 1337)
    env.message_call(c.address, value=1337)

    assert c.get_balance() == 1337
    assert env.get_balance(c.address) == 1337
    assert env.get_balance(env.deployer) == 0
