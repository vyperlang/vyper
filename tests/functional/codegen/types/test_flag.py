def test_values_should_be_increasing_ints(get_contract):
    code = """
flag Action:
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


def test_flag_storage(get_contract):
    code = """
flag Actions:
    BUY
    SELL
    CANCEL

action: public(Actions)

@external
def set_and_get(a: Actions) -> Actions:
    self.action = a
    return self.action
    """
    c = get_contract(code)
    for i in range(5):
        assert c.set_and_get(i) == i
        c.set_and_get(i, transact={})
        assert c.action() == i


def test_eq_neq(get_contract):
    code = """
flag Roles:
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
        assert c.is_boss(2**i) is False
        assert c.is_not_boss(2**i) is True

    assert c.is_boss(2**4) is True
    assert c.is_not_boss(2**4) is False


def test_bitwise(get_contract, tx_failed):
    code = """
flag Roles:
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

@external
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

    assert c.bor_arg(0b00001, 0b00100) == 0b00001 | 0b00100 == 0b00101
    # LHS: USER | ADMIN | CEO; RHS: USER | MANAGER | CEO
    assert c.band_arg(0b10101, 0b11001) == 0b10101 & 0b11001 == 0b10001

    assert c.bxor_arg(0b10101, 0b11001) == 0b10101 ^ 0b11001 == 0b01100

    assert c.binv_arg(0b01101) == ~0b01101 % 32 == 0b10010
    assert c.binv_arg(0b11111) == 0b00000
    assert c.binv_arg(0b00000) == 0b11111

    # LHS is out of bound
    with tx_failed():
        c.bor_arg(32, 3)
    with tx_failed():
        c.band_arg(32, 3)
    with tx_failed():
        c.bxor_arg(32, 3)
    with tx_failed():
        c.binv_arg(32)

    # RHS
    with tx_failed():
        c.bor_arg(3, 32)
    with tx_failed():
        c.band_arg(3, 32)
    with tx_failed():
        c.bxor_arg(3, 32)


def test_augassign_storage(get_contract, w3, tx_failed):
    code = """
flag Roles:
    ADMIN
    MINTER

roles: public(HashMap[address, Roles])

@deploy
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

    assert c.roles(admin_address) == 0b01
    assert c.roles(minter_address) == 0b10

    # admin is not a minter
    with tx_failed():
        c.checkMinter(admin_address)

    c.addMinter(admin_address, transact={})

    # now, admin is a minter
    assert c.roles(admin_address) == 0b11
    c.checkMinter(admin_address)

    # revoke minter
    c.revokeMinter(admin_address, transact={})
    assert c.roles(admin_address) == 0b01
    with tx_failed():
        c.checkMinter(admin_address)

    # flip minter
    c.flipMinter(admin_address, transact={})
    assert c.roles(admin_address) == 0b11
    c.checkMinter(admin_address)

    # flip minter
    c.flipMinter(admin_address, transact={})
    assert c.roles(admin_address) == 0b01
    with tx_failed():
        c.checkMinter(admin_address)


def test_in_flag(get_contract_with_gas_estimation):
    code = """
flag Roles:
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
def bar2(a: Roles) -> bool:
    return a not in (Roles.USER | Roles.ADMIN)

@external
def baz(a: Roles) -> bool:
    x: Roles = Roles.USER | Roles.ADMIN | Roles.CEO
    y: Roles = x ^ (Roles.MANAGER | Roles.CEO)  # flip off CEO, flip on MANAGER
    return a in (x & y)

    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True

    # CEO MANAGER ADMIN STAFF USER
    #   1       1     1     1    1

    assert c.bar(0b00001) is True  # Roles.USER should pass
    assert c.bar(0b00010) is False  # Roles.STAFF should fail

    assert c.bar2(0b00001) is False  # Roles.USER should fail
    assert c.bar2(0b00010) is True  # Roles.STAFF should pass

    assert c.baz(0b00001) is True  # Roles.USER should pass
    assert c.baz(0b00100) is True  # Roles.ADMIN should pass
    assert c.baz(0b01000) is False  # Roles.MANAGER should fail


def test_struct_with_flag(get_contract_with_gas_estimation):
    code = """
flag Foobar:
    FOO
    BAR

struct Foo:
    a: uint256
    b: Foobar

@external
def get_flag_from_struct() -> Foobar:
    f: Foo = Foo(a=1, b=Foobar.BAR)
    return f.b
    """
    c = get_contract_with_gas_estimation(code)
    assert c.get_flag_from_struct() == 2


def test_mapping_with_flag(get_contract_with_gas_estimation):
    code = """
flag Foobar:
    FOO
    BAR

fb: HashMap[Foobar, uint256]

@external
def get_key(f: Foobar, i: uint256) -> uint256:
    self.fb[f] = i
    return self.fb[f]
    """
    c = get_contract_with_gas_estimation(code)
    assert c.get_key(1, 777) == 777
