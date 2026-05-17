import warnings


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

    owner = env.accounts[0]
    val = 10
    env.set_balance(env.deployer, val)
    with warnings.catch_warnings(record=True) as w:
        c = get_contract(contract, owner, value=val)
    assert env.get_balance(owner) == 0
    assert env.get_balance(c.address) == val
    c.refund()
    assert env.get_balance(c.address) == 0
    assert env.get_balance(owner) == val

    check_selfdestruct_warning(w)


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
    with warnings.catch_warnings(record=True) as w:
        c = get_contract(contract, owner, recipient, value=val)
    assert env.get_balance(owner) == 0
    assert env.get_balance(recipient) == 0
    assert env.get_balance(c.address) == val
    c.refund()
    assert env.get_balance(owner) == val // 2
    assert env.get_balance(recipient) == val // 2
    assert env.get_balance(c.address) == 0

    check_selfdestruct_warning(w)


def check_selfdestruct_warning(w):
    expected = "`selfdestruct` is deprecated!"
    expected += " The opcode is no longer recommended for use."
    assert len(w) == 1, [s.message for s in w]
    assert str(w[0].message).startswith(expected)
