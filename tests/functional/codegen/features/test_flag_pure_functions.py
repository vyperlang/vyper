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


def test_mixed_pure_function_features(get_contract):
    """Test that other pure function features still work alongside flags"""
    code = """
flag Action:
    BUY
    SELL

struct Point:
    x: uint256
    y: uint256

@pure
@external
def get_action_and_point() -> (Action, Point):
    return Action.BUY, Point(x=10, y=20)

@pure
@external
def pure_math(a: uint256, b: uint256) -> uint256:
    return a + b
    """
    c = get_contract(code)
    action, point = c.get_action_and_point()
    assert action == 1  # BUY
    assert point == (10, 20)
    assert c.pure_math(5, 7) == 12
