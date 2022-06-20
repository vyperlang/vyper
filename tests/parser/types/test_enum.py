def test_values_should_be_increasing_ints(get_contract):
    code = """
enum Action:
    BUY
    SELL
    CANCEL

@external
@view
def buy() -> Action:
    return Action.BUY

@external
@view
def sell() -> Action:
    return Action.SELL

@external
@view
def cancel() -> Action:
    return Action.CANCEL
    """
    c = get_contract(code)
    assert c.buy() == 1
    assert c.sell() == 2
    assert c.cancel() == 4


def test_eq_neq(get_contract):
    code = """
enum Roles:
    USER
    STAFF
    ADMIN
    MANAGER
    CEO

@external
def is_boss(a: Roles) -> bool:
    return a == Roles.CEO

@external
def is_not_boss(a: Roles) -> bool:
    return a != Roles.CEO
    """
    c = get_contract(code)

    for i in range(4):
        assert c.is_boss(2 ** i) is False
        assert c.is_not_boss(2 ** i) is True

    assert c.is_boss(2 ** 4) is True
    assert c.is_not_boss(2 ** 4) is False


def test_bitwise(get_contract, assert_tx_failed):
    code = """
enum Roles:
    USER
    STAFF
    ADMIN
    MANAGER
    CEO

@external
def bor() -> Roles:
    return Roles.USER | Roles.CEO

@external
def band() -> Roles:
    c: Roles = Roles.USER | Roles.CEO
    return c & Roles.USER

@external
def bxor() -> Roles:
    c: Roles = Roles.USER | Roles.CEO
    return c ^ Roles.USER

def binv() -> Roles:
    c: Roles = Roles.USER
    return ~c

@external
def bor_arg(a: Roles, b: Roles) -> Roles:
    return a | b

@external
def band_arg(a: Roles, b: Roles) -> Roles:
    return a & b

@external
def bxor_arg(a: Roles, b: Roles) -> Roles:
    return a ^ b

@external
def binv_arg(a: Roles) -> Roles:
    return ~a
    """
    c = get_contract(code)
    assert c.bor() == 17
    assert c.band() == 1
    assert c.bxor() == 16

    assert c.bor_arg(1, 4) == 5
    # LHS: USER | ADMIN | CEO; RHS: USER | MANAGER | CEO
    assert c.band_arg(21, 25) == 17

    assert c.bxor_arg(21, 25) == 21 ^ 25

    assert c.binv_arg(0b01101) == 0b10010
    assert c.binv_arg(0b11111) == 0

    # LHS is out of bound
    assert_tx_failed(lambda: c.bor_arg(32, 3))
    assert_tx_failed(lambda: c.band_arg(32, 3))
    assert_tx_failed(lambda: c.bxor_arg(32, 3))
    assert_tx_failed(lambda: c.binv_arg(32))

    # RHS
    assert_tx_failed(lambda: c.bor_arg(3, 32))
    assert_tx_failed(lambda: c.band_arg(3, 32))
    assert_tx_failed(lambda: c.bxor_arg(3, 32))


def test_augassign_storage(get_contract, w3, assert_tx_failed):
    code = """
enum Roles:
    ADMIN
    MINTER

roles: public(HashMap[address, Roles])

@external
def __init__():
    self.roles[msg.sender] = Roles.ADMIN

@external
def addMinter(minter: address):
    assert self.roles[msg.sender] in Roles.ADMIN
    self.roles[minter] |= Roles.MINTER

@external
def revokeMinter(minter: address):
    assert self.roles[msg.sender] in Roles.ADMIN
    self.roles[minter] &= ~Roles.MINTER

@external
def flipMinter(minter: address):
    assert self.roles[msg.sender] in Roles.ADMIN
    self.roles[minter] ^= Roles.MINTER

@external
def checkMinter(minter: address):
    assert Roles.MINTER in self.roles[minter]
    """
    c = get_contract(code)

    # check admin
    admin_address = w3.eth.accounts[0]
    minter_address = w3.eth.accounts[1]

    # add minter
    c.addMinter(minter_address, transact={})
    c.checkMinter(minter_address)

    assert c.roles(admin_address) == 2 ** 0
    assert c.roles(minter_address) == 2 ** 1

    # admin is not a minter
    assert_tx_failed(lambda: c.checkMinter(admin_address))

    c.addMinter(admin_address, transact={})

    # now, admin is a minter
    assert c.roles(admin_address) == 2 ** 0 | 2 ** 1
    c.checkMinter(admin_address)

    # revoke minter
    c.revokeMinter(admin_address, transact={})
    assert c.roles(admin_address) == 2 ** 0
    assert_tx_failed(lambda: c.checkMinter(admin_address))

    # flip minter
    c.flipMinter(admin_address, transact={})
    assert c.roles(admin_address) == 2 ** 0 | 2 ** 1
    c.checkMinter(admin_address)

    # flip minter
    c.flipMinter(admin_address, transact={})
    assert c.roles(admin_address) == 2 ** 0
    assert_tx_failed(lambda: c.checkMinter(admin_address))


def test_for_in_enum(get_contract_with_gas_estimation):
    code = """
enum Roles:
    USER
    STAFF
    ADMIN
    MANAGER
    CEO

@external
def foo() -> bool:
    return Roles.USER in (Roles.USER | Roles.ADMIN)

@external
def bar(a: Roles) -> bool:
    return a in (Roles.USER | Roles.ADMIN)

@external
def baz(a: Roles) -> bool:
    x: Roles = Roles.USER | Roles.ADMIN | Roles.CEO
    y: Roles = x ^ (Roles.MANAGER | Roles.CEO)  # flip off CEO, flip on MANAGER
    return a in (x & y)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True

    assert c.bar(1) is True  # Roles.USER should pass
    assert c.bar(2) is False  # Roles.STAFF should fail

    assert c.baz(1) is True  # Roles.USER should pass
    assert c.baz(4) is True  # Roles.ADMIN should pass
    assert c.baz(8) is False  # Roles.MANAGER should fail
