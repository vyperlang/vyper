from vyper.exceptions import (
    ParserException,
    ConstancyViolationException,
    InvalidLiteralException,
)


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


def test_valid_literal_increment(get_contract_with_gas_estimation):
    code = """
storx: uint256

@public
def foo1() -> int128:
    x: int128 = 122
    x += 1
    return x

@public
def foo2() -> uint256:
    x: uint256 = 122
    x += 1
    return x

@public
def foo3(y: uint256) -> uint256:
    self.storx = y
    self.storx += 1
    return self.storx
"""
    c = get_contract_with_gas_estimation(code)

    assert c.foo1() == 123
    assert c.foo2() == 123
    assert c.foo3(11) == 12


def test_invalid_uin256_assignment(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
storx: uint256

@public
def foo2() -> uint256:
    x: uint256 = -1
    x += 1
    return x
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidLiteralException)


def test_invalid_uin256_assignment_calculate_literals(get_contract_with_gas_estimation):
    code = """
storx: uint256

@public
def foo2() -> uint256:
    x: uint256
    x = 3 * 4 / 2 + 1 - 2
    return x
"""
    c = get_contract_with_gas_estimation(code)

    assert c.foo2() == 5


def test_calculate_literals_invalid(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo2() -> uint256:
    x: uint256
    x = 3 ^ 3  # invalid operator
    return x
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ParserException)


# See #838. Confirm that nested keys and structs work properly.
def test_nested_map_key_works(get_contract_with_gas_estimation):
    code = """
test_map1: {a: int128, b: int128 }[int128]
test_map2: {c: int128, d: int128}[int128]

@public
def set():
    self.test_map1[1].a = 333
    self.test_map2[333].c = 111


@public
def get(i: int128) -> int128:
    idx: int128 = self.test_map1[i].a
    return self.test_map2[idx].c
    """
    c = get_contract_with_gas_estimation(code)
    assert c.set(transact={})
    assert c.get(1) == 111


def test_nested_map_key_problem(get_contract_with_gas_estimation):
    code = """
test_map1: {a: int128, b: int128 }[int128]
test_map2: {c: int128, d: int128}[int128]

@public
def set():
    self.test_map1[1].a = 333
    self.test_map2[333].c = 111


@public
def get() -> int128:
    return self.test_map2[self.test_map1[1].a].c
    """
    c = get_contract_with_gas_estimation(code)
    assert c.set(transact={})
    assert c.get() == 111
