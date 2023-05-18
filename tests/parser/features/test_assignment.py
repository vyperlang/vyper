import pytest

from vyper.exceptions import ImmutableViolation, InvalidType, TypeMismatch


def test_augassign(get_contract_with_gas_estimation):
    augassign_test = """
@external
def augadd(x: int128, y: int128) -> int128:
    z: int128 = x
    z += y
    return z

@external
def augmul(x: int128, y: int128) -> int128:
    z: int128 = x
    z *= y
    return z

@external
def augsub(x: int128, y: int128) -> int128:
    z: int128 = x
    z -= y
    return z

@external
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
    print("Passed aug-assignment test")


def test_invalid_assign(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def foo(x: int128):
    x = 5
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ImmutableViolation)


def test_invalid_augassign(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def foo(x: int128):
    x += 5
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ImmutableViolation)


def test_valid_literal_increment(get_contract_with_gas_estimation):
    code = """
storx: uint256

@external
def foo1() -> int128:
    x: int128 = 122
    x += 1
    return x

@external
def foo2() -> uint256:
    x: uint256 = 122
    x += 1
    return x

@external
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

@external
def foo2() -> uint256:
    x: uint256 = -1
    x += 1
    return x
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidType)


def test_invalid_uin256_assignment_calculate_literals(get_contract_with_gas_estimation):
    code = """
storx: uint256

@external
def foo2() -> uint256:
    x: uint256 = 0
    x = 3 * 4 / 2 + 1 - 2
    return x
"""
    c = get_contract_with_gas_estimation(code)

    assert c.foo2() == 5


# See #838. Confirm that nested keys and structs work properly.
def test_nested_map_key_works(get_contract_with_gas_estimation):
    code = """
struct X:
    a: int128
    b: int128
struct Y:
    c: int128
    d: int128
test_map1: HashMap[int128, X]
test_map2: HashMap[int128, Y]

@external
def set():
    self.test_map1[1].a = 333
    self.test_map2[333].c = 111


@external
def get(i: int128) -> int128:
    idx: int128 = self.test_map1[i].a
    return self.test_map2[idx].c
    """
    c = get_contract_with_gas_estimation(code)
    assert c.set(transact={})
    assert c.get(1) == 111


def test_nested_map_key_problem(get_contract_with_gas_estimation):
    code = """
struct X:
    a: int128
    b: int128
struct Y:
    c: int128
    d: int128
test_map1: HashMap[int128, X]
test_map2: HashMap[int128, Y]

@external
def set():
    self.test_map1[1].a = 333
    self.test_map2[333].c = 111


@external
def get() -> int128:
    return self.test_map2[self.test_map1[1].a].c
    """
    c = get_contract_with_gas_estimation(code)
    assert c.set(transact={})
    assert c.get() == 111


@pytest.mark.parametrize(
    "contract",
    [
        """
@external
def foo():
    y: int128 = 1
    z: decimal = y
    """,
        """
@external
def foo():
    y: int128 = 1
    z: decimal = 0.0
    z = y
    """,
        """
@external
def foo():
    y: bool = False
    z: decimal = y
    """,
        """
@external
def foo():
    y: bool = False
    z: decimal = 0.0
    z = y
    """,
        """
@external
def foo():
    y: uint256 = 1
    z: int128 = y
    """,
        """
@external
def foo():
    y: uint256 = 1
    z: int128 = 0
    z = y
    """,
        """
@external
def foo():
    y: int128 = 1
    z: bytes32 = y
    """,
        """
@external
def foo():
    y: int128 = 1
    z: bytes32 = EMPTY_BYTES32
    z = y
    """,
        """
@external
def foo():
    y: uint256 = 1
    z: bytes32 = y
    """,
        """
@external
def foo():
    y: uint256 = 1
    z: bytes32 = EMPTY_BYTES32
    z = y
    """,
    ],
)
def test_invalid_implicit_conversions(
    contract, assert_compile_failed, get_contract_with_gas_estimation
):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), TypeMismatch)


def test_invalid_nonetype_assignment(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@internal
def bar():
    pass

@external
def foo():
    ret : bool = self.bar()
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), InvalidType)


def test_assign_rhs_lhs_overlap(get_contract):
    # GH issue 2418
    code = """
@external
def bug(xs: uint256[2]) -> uint256[2]:
    # Initial value
    ys: uint256[2] = xs
    ys = [ys[1], ys[0]]
    return ys
    """
    c = get_contract(code)

    assert c.bug([1, 2]) == [2, 1]


def test_assign_rhs_lhs_partial_overlap(get_contract):
    # GH issue 2418, generalize when lhs is not only dependency of rhs.
    code = """
@external
def bug(xs: uint256[2]) -> uint256[2]:
    # Initial value
    ys: uint256[2] = xs
    ys = [xs[1], ys[0]]
    return ys
    """
    c = get_contract(code)

    assert c.bug([1, 2]) == [2, 1]


def test_assign_rhs_lhs_overlap_dynarray(get_contract):
    # GH issue 2418, generalize to dynarrays
    code = """
@external
def bug(xs: DynArray[uint256, 2]) -> DynArray[uint256, 2]:
    ys: DynArray[uint256, 2] = xs
    ys = [ys[1], ys[0]]
    return ys
    """
    c = get_contract(code)
    assert c.bug([1, 2]) == [2, 1]


def test_assign_rhs_lhs_overlap_struct(get_contract):
    # GH issue 2418, generalize to structs
    code = """
struct Point:
    x: uint256
    y: uint256

@external
def bug(p: Point) -> Point:
    t: Point = p
    t = Point({x: t.y, y: t.x})
    return t
    """
    c = get_contract(code)
    assert c.bug((1, 2)) == (2, 1)
