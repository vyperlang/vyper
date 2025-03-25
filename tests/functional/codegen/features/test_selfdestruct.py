def test_selfdestruct_with_storage_variable(env, get_contract):
    contract = """
owner: address

@deploy
@payable
def __init__(o: address):
    self.owner = o

@external
def refund():
    selfdestruct(self.owner)
    """

    a0 = env.accounts[0]
    val = 10
    env.set_balance(env.deployer, val)
    c = get_contract(contract, a0, value=val)
    assert env.get_balance(a0) == 0
    assert env.get_balance(c.address) == val
    c.refund()
    assert env.get_balance(a0) == val


def test_selfdestruct_double_eval(env, get_contract):
    val = 10
    contract = f"""
owner: address
recipient: address

@deploy
@payable
def __init__(o: address, r: address):
    self.owner = o
    self.recipient = r

def pay() -> address:
    send(self.recipient, {val // 2})
    return self.owner


@external
def refund():
    selfdestruct(self.pay())
    """

    owner, recipient = env.accounts[:2]
    val = 10
    env.set_balance(env.deployer, val)
    c = get_contract(contract, owner, recipient, value=val)
    assert env.get_balance(owner) == 0
    assert env.get_balance(recipient) == 0
    assert env.get_balance(c.address) == val
    c.refund()
    assert env.get_balance(owner) == val // 2
    assert env.get_balance(recipient) == val // 2
