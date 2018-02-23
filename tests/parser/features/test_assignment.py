from vyper.exceptions import ConstancyViolationException


def test_augassign(get_contract_with_gas_estimation):
    augassign_test = """
@public
def augadd(x: int128, y: int128) -> int128:
    z: int128 = x
    z += y
    return z

@public
def augmul(x: int128, y: int128) -> int128:
    z: int128 = x
    z *= y
    return z

@public
def augsub(x: int128, y: int128) -> int128:
    z: int128 = x
    z -= y
    return z

@public
def augmod(x: int128, y: int128) -> int128:
    z: int128 = x
    z %= y
    return z
    """

    c = get_contract_with_gas_estimation(augassign_test)

    assert c.augadd(5, 12) == 17
    assert c.augmul(5, 12) == 60
    assert c.augsub(5, 12) == -7
    assert c.augmod(5, 12) == 5
    print('Passed aug-assignment test')


def test_invalid_assign(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: int128):
    x = 5
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ConstancyViolationException)


def test_invalid_augassign(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: int128):
    x += 5
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ConstancyViolationException)
