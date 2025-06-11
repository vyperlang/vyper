import pytest

from tests.utils import decimal_to_int


def test_storage_variable_initialization(get_contract):
    code = """
x: uint256 = 42
y: int128 = -100
z: bool = True
w: address = 0x0000000000000000000000000000000000000123

@external
@view
def get_x() -> uint256:
    return self.x

@external
@view
def get_y() -> int128:
    return self.y

@external
@view
def get_z() -> bool:
    return self.z

@external
@view
def get_w() -> address:
    return self.w
    """

    c = get_contract(code)
    assert c.get_x() == 42
    assert c.get_y() == -100
    assert c.get_z() is True
    assert c.get_w() == "0x0000000000000000000000000000000000000123"


def test_storage_variable_initialization_with_constructor_override(get_contract):
    code = """
x: uint256 = 42
y: int128 = -100

@deploy
def __init__(new_x: uint256):
    self.x = new_x  # Override x
    # y keeps its initialized value

@external
@view
def get_x() -> uint256:
    return self.x

@external
@view
def get_y() -> int128:
    return self.y
    """

    c = get_contract(code, 999)
    assert c.get_x() == 999  # overridden by constructor
    assert c.get_y() == -100  # keeps initialized value


def test_immutable_initialization(get_contract):
    code = """
X: immutable(uint256) = 42
Y: immutable(int128) = -100

@deploy
def __init__(override_x: uint256):
    X = override_x  # Override X
    # Y keeps initialized value

@external
@view
def get_x() -> uint256:
    return X

@external
@view
def get_y() -> int128:
    return Y
    """

    c = get_contract(code, 123)
    assert c.get_x() == 123  # overridden
    assert c.get_y() == -100  # keeps initialized value


def test_complex_initialization_expressions(get_contract):
    code = """
# Test various literal types and constant expressions
a: uint256 = 1024  # 2 ** 10
b: int128 = -100   # -50 * 2
c: decimal = 3.14159
d: bool = False
e: bytes32 = 0x1234567890123456789012345678901234567890123456789012345678901234

@external
@view
def get_a() -> uint256:
    return self.a

@external
@view
def get_b() -> int128:
    return self.b

@external
@view
def get_c() -> decimal:
    return self.c

@external
@view
def get_d() -> bool:
    return self.d

@external
@view
def get_e() -> bytes32:
    return self.e
    """

    c = get_contract(code)
    assert c.get_a() == 1024
    assert c.get_b() == -100
    assert c.get_c() == decimal_to_int("3.14159")
    assert c.get_d() is False
    assert c.get_e() == b"\x124Vx\x90\x124Vx\x90\x124Vx\x90\x124Vx\x90\x124Vx\x90\x124Vx\x90\x124"


def test_initialization_order(get_contract):
    """Test that initializations happen in declaration order"""
    code = """
a: uint256 = 1
b: uint256 = 2
c: uint256 = 3

@deploy
def __init__():
    # Check they were initialized in order
    assert self.a == 1
    assert self.b == 2
    assert self.c == 3

    # Now override b
    self.b = 20

@external
@view
def get_a() -> uint256:
    return self.a

@external
@view
def get_b() -> uint256:
    return self.b

@external
@view
def get_c() -> uint256:
    return self.c
    """

    c = get_contract(code)
    assert c.get_a() == 1
    assert c.get_b() == 20  # overridden in constructor
    assert c.get_c() == 3


def test_no_constructor_with_initialization(get_contract):
    """Test that initialization works even without a constructor"""
    code = """
x: uint256 = 100
y: bool = True

@external
@view
def get_x() -> uint256:
    return self.x

@external
@view
def get_y() -> bool:
    return self.y
    """

    c = get_contract(code)
    assert c.get_x() == 100
    assert c.get_y() is True


def test_mixed_initialized_and_uninitialized(get_contract):
    """Test mixing initialized and uninitialized variables"""
    code = """
a: uint256 = 42  # initialized
b: uint256       # not initialized, should be 0
c: int128 = -50  # initialized
d: int128        # not initialized, should be 0

@external
@view
def get_values() -> (uint256, uint256, int128, int128):
    return self.a, self.b, self.c, self.d
    """

    c = get_contract(code)
    a, b, c_val, d = c.get_values()
    assert a == 42
    assert b == 0
    assert c_val == -50
    assert d == 0


def test_public_variable_initialization(get_contract):
    """Test that public variables with initializers work correctly"""
    code = """
x: public(uint256) = 12345
y: public(bool) = True
z: public(address) = 0x0000000000000000000000000000000000000aBc
    """

    c = get_contract(code)
    # public variables automatically get getter functions
    assert c.x() == 12345
    assert c.y() is True
    assert c.z() == "0x0000000000000000000000000000000000000aBc"


@pytest.mark.requires_evm_version("cancun")
def test_transient_storage_initialization(get_contract):
    """Test initialization of transient storage variables"""
    code = """
#pragma evm-version cancun

x: transient(uint256) = 42
y: transient(bool) = True

# Storage variables to capture transient values during deployment
stored_x: uint256
stored_y: bool

@deploy
def __init__():
    # Capture the initialized transient values
    self.stored_x = self.x
    self.stored_y = self.y

@external
@view
def get_stored_x() -> uint256:
    return self.stored_x

@external
@view
def get_stored_y() -> bool:
    return self.stored_y

@external
def get_x() -> uint256:
    return self.x

@external
def get_y() -> bool:
    return self.y
    """

    c = get_contract(code)

    # Verify that transient variables were initialized during deployment
    assert c.get_stored_x() == 42
    assert c.get_stored_y() is True

    # In test environment, all calls happen in the same transaction,
    # so transient storage retains its value from initialization
    assert c.get_x() == 42
    assert c.get_y() is True


def test_constructor_with_conditional_override(get_contract):
    """Test conditional logic in constructor that may override initialized values"""
    code = """
x: uint256 = 100
y: uint256 = 200
z: uint256 = 300

@deploy
def __init__(override_flag: uint256):
    if override_flag == 1:
        self.x = 111
    elif override_flag == 2:
        self.y = 222
    else:
        self.z = 333

    # nested conditions
    if self.x > 100:
        if self.y == 200:
            self.z = 999

@external
@view
def get_values() -> (uint256, uint256, uint256):
    return self.x, self.y, self.z
    """

    # Test case 1: override_flag == 1
    c1 = get_contract(code, 1)
    x, y, z = c1.get_values()
    assert x == 111  # overridden
    assert y == 200  # kept initial
    assert z == 999  # overridden by nested condition

    # Test case 2: override_flag == 2
    c2 = get_contract(code, 2)
    x, y, z = c2.get_values()
    assert x == 100  # kept initial
    assert y == 222  # overridden
    assert z == 300  # kept initial

    # Test case 3: override_flag == other
    c3 = get_contract(code, 3)
    x, y, z = c3.get_values()
    assert x == 100  # kept initial
    assert y == 200  # kept initial
    assert z == 333  # overridden


def test_constructor_with_loop_override(get_contract):
    """Test loops in constructor that modify initialized values"""
    code = """
counter: uint256 = 1000
values: uint256[10] = empty(uint256[10])

@deploy
def __init__(iterations: uint256):
    # Initialize some array values based on counter
    for i: uint256 in range(10):
        self.values[i] = self.counter + i

    # Conditionally modify counter in a loop
    for i: uint256 in range(10):
        if i < iterations:
            self.counter += 10
        else:
            break

@external
@view
def get_counter() -> uint256:
    return self.counter

@external
@view
def get_value(idx: uint256) -> uint256:
    return self.values[idx]
    """

    # Test with 5 iterations
    c = get_contract(code, 5)
    assert c.get_counter() == 1050  # 1000 + (5 * 10)
    assert c.get_value(0) == 1000  # initial counter value
    assert c.get_value(5) == 1005  # counter + 5


def test_early_return_in_constructor(get_contract):
    """Test early returns in constructor don't skip initializations"""
    code = """
a: uint256 = 100
b: uint256 = 200
c: uint256 = 300

@deploy
def __init__(early_exit: bool):
    # Variable initializations should have already happened
    assert self.a == 100
    assert self.b == 200
    assert self.c == 300

    if early_exit:
        self.a = 111
        return  # early return

    # This code only runs if not early_exit
    self.b = 222
    self.c = 333

@external
@view
def get_values() -> (uint256, uint256, uint256):
    return self.a, self.b, self.c
    """

    # Test early exit
    c1 = get_contract(code, True)
    a, b, c = c1.get_values()
    assert a == 111  # modified before return
    assert b == 200  # kept initial (after return)
    assert c == 300  # kept initial (after return)

    # Test normal flow
    c2 = get_contract(code, False)
    a, b, c = c2.get_values()
    assert a == 100  # kept initial
    assert b == 222  # modified
    assert c == 333  # modified


def test_constructor_with_assert_on_initialized_values(get_contract):
    """Test that constructor can make assertions about initialized values"""
    code = """
MIN_VALUE: constant(uint256) = 50
MAX_VALUE: constant(uint256) = 150

x: uint256 = 100
y: uint256 = 75
z: uint256 = 125

@deploy
def __init__(adjustment: int128):
    # Assert initial values are in expected range
    assert self.x >= MIN_VALUE and self.x <= MAX_VALUE
    assert self.y >= MIN_VALUE and self.y <= MAX_VALUE
    assert self.z >= MIN_VALUE and self.z <= MAX_VALUE

    # Adjust values but keep in range
    if adjustment > 0:
        new_x: uint256 = self.x + convert(adjustment, uint256)
        if new_x <= MAX_VALUE:
            self.x = new_x
    elif adjustment < 0:
        sub_amount: uint256 = convert(-adjustment, uint256)
        if self.x >= MIN_VALUE + sub_amount:
            self.x = self.x - sub_amount

@external
@view
def get_x() -> uint256:
    return self.x
    """

    # Test positive adjustment
    c1 = get_contract(code, 25)
    assert c1.get_x() == 125  # 100 + 25

    # Test negative adjustment
    c2 = get_contract(code, -40)
    assert c2.get_x() == 60  # 100 - 40

    # Test adjustment that would exceed bounds
    c3 = get_contract(code, 60)
    assert c3.get_x() == 100  # unchanged because 100 + 60 > 150


def test_msg_sender_initialization(env, get_contract, tx_failed):
    """Test that msg.sender can be used in variable initialization"""
    code = """
owner: address = msg.sender
backup_owner: address = msg.sender

@external
@view
def get_owner() -> address:
    return self.owner

@external
@view
def get_backup_owner() -> address:
    return self.backup_owner

@external
def set_owner(new_owner: address):
    assert msg.sender == self.owner, "Only owner can change owner"
    self.owner = new_owner
    """

    c = get_contract(code)

    # Check that owner and backup_owner were initialized to deployer
    assert c.get_owner() == env.deployer
    assert c.get_backup_owner() == env.deployer

    # Test that owner can be changed by the current owner
    new_owner = env.accounts[1]
    c.set_owner(new_owner)
    assert c.get_owner() == new_owner
    assert c.get_backup_owner() == env.deployer  # unchanged

    # Test that non-owner cannot change owner
    with tx_failed():
        env.set_balance(env.accounts[2], 10**18)
        c.set_owner(env.accounts[2], sender=env.accounts[2])


def test_msg_sender_with_constructor_override(env, get_contract):
    """Test msg.sender initialization with constructor override"""
    code = """
owner: address = msg.sender
admin: address = msg.sender

@deploy
def __init__(admin_address: address):
    # Override admin but keep owner as msg.sender
    self.admin = admin_address

@external
@view
def get_owner() -> address:
    return self.owner

@external
@view
def get_admin() -> address:
    return self.admin
    """

    admin_addr = env.accounts[1]
    c = get_contract(code, admin_addr)

    # Owner should be the deployer (msg.sender during initialization)
    assert c.get_owner() == env.deployer
    # Admin should be overridden by constructor
    assert c.get_admin() == admin_addr


def test_runtime_constants_initialization(env, get_contract):
    """Test that runtime constants (block, tx, msg, chain) can be used in initializers"""
    code = """
# All of these are runtime constants and should be allowed
deployer: address = msg.sender
origin: address = tx.origin
deploy_block: uint256 = block.number
deploy_timestamp: uint256 = block.timestamp
chain_id: uint256 = chain.id

@external
@view
def get_deployer() -> address:
    return self.deployer

@external
@view
def get_origin() -> address:
    return self.origin

@external
@view
def get_deploy_block() -> uint256:
    return self.deploy_block

@external
@view
def get_deploy_timestamp() -> uint256:
    return self.deploy_timestamp

@external
@view
def get_chain_id() -> uint256:
    return self.chain_id
    """

    # Record environment values at deployment
    c = get_contract(code)

    # Check all values were initialized correctly
    assert c.get_deployer() == env.deployer
    assert c.get_origin() == env.deployer  # In tests, origin == sender

    # Block number should match current environment
    assert c.get_deploy_block() == env.block_number

    # Timestamp should match current environment
    assert c.get_deploy_timestamp() == env.timestamp

    # Chain ID should be the default (1)
    assert c.get_chain_id() == env.DEFAULT_CHAIN_ID


def test_self_initialization(get_contract, env):
    """Test that self can be used as an initializer"""
    code = """
owner: address = self
backup: address = self

@external
@view
def get_owner() -> address:
    return self.owner

@external
@view
def get_backup() -> address:
    return self.backup
    """

    c = get_contract(code)

    # both should be set to the contract's address
    assert c.get_owner() == c.address
    assert c.get_backup() == c.address


def test_self_initialization_with_override(get_contract, env):
    """Test self initialization with constructor override"""
    code = """
owner: address = self

@deploy
def __init__():
    # override with msg.sender
    self.owner = msg.sender

@external
@view
def get_owner() -> address:
    return self.owner
    """

    c = get_contract(code)

    # should be overridden to deployer
    assert c.get_owner() == env.deployer
