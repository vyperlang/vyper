def test_flag_members_in_pure_functions(get_contract):
    """Test that flag members can be used in pure functions since they are
    compile-time constants"""
    code = """
flag Action:
    BUY
    SELL
    CANCEL

@pure
@external
def get_buy_action() -> Action:
    return Action.BUY

@pure
@external
def get_sell_action() -> Action:
    return Action.SELL

@pure
@external
def get_cancel_action() -> Action:
    return Action.CANCEL
    """
    c = get_contract(code)
    assert c.get_buy_action() == 1  # 2^0
    assert c.get_sell_action() == 2  # 2^1
    assert c.get_cancel_action() == 4  # 2^2


def test_flag_operations_in_pure_functions(get_contract):
    """Test that flag operations work in pure functions"""
    code = """
flag Permissions:
    READ
    WRITE
    EXECUTE

@pure
@external
def get_read_write() -> Permissions:
    return Permissions.READ | Permissions.WRITE

@pure
@external
def check_read_permission(perms: Permissions) -> bool:
    return Permissions.READ in perms

@pure
@external
def combine_all() -> Permissions:
    return Permissions.READ | Permissions.WRITE | Permissions.EXECUTE
    """
    c = get_contract(code)
    assert c.get_read_write() == 3  # 1 | 2 = 3
    assert c.check_read_permission(1) is True  # READ permission
    assert c.check_read_permission(2) is False  # WRITE permission only
    assert c.combine_all() == 7  # 1 | 2 | 4 = 7


def test_flag_conditionals_in_pure_functions(get_contract):
    """Test flags in conditional expressions within pure functions"""
    code = """
flag Status:
    ACTIVE
    INACTIVE
    PENDING

@pure
@external
def classify_status(status: Status) -> uint256:
    if status == Status.ACTIVE:
        return 100
    elif status == Status.PENDING:
        return 50
    else:
        return 0
    """
    c = get_contract(code)
    assert c.classify_status(1) == 100  # ACTIVE
    assert c.classify_status(4) == 50  # PENDING
    assert c.classify_status(2) == 0  # INACTIVE


def test_access_flag_from_another_module(get_contract, make_input_bundle):
    """Test flag access even if the attribute comes from another module (eg lib1.flag.foo)"""
    code = """
import lib1

@pure
@external
def foo() -> lib1.Action:
    return lib1.Action.BUY

    """
    lib1 = """
flag Action:
    BUY
    SELL
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(code, input_bundle=input_bundle)
    assert c.foo() == 1  # BUY


def test_internal_pure_accessing_flag(get_contract, make_input_bundle):
    """Test flag accesses in internal pure functions"""
    code = """
import lib1

@pure
def bar() -> lib1.Action:
    return lib1.Action.BUY

@pure
@external
def foo() -> lib1.Action:
    return self.bar()

    """
    lib1 = """
flag Action:
    BUY
    SELL
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(code, input_bundle=input_bundle)
    assert c.foo() == 1  # BUY


def test_flag_access_in_loop(get_contract, make_input_bundle):
    """Test flag accesses in a for loop"""
    code = """

flag Action:
    BUY
    SELL

@pure
@external
def foo() -> uint256:
    cnt: uint256 = 0
    for i: uint256 in range(10):
        cnt += convert(Action.SELL, uint256)
    return cnt
"""
    c = get_contract(code)
    assert c.foo() == 10 * 2
