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


@pytest.mark.parametrize(
    "typ,in_val,out_val",
    [
        ("uint256", 77, 123),
        ("uint256[3]", [1, 2, 3], [4, 5, 6]),
        ("DynArray[uint256, 3]", [1, 2, 3], [4, 5, 6]),
        ("Bytes[5]", b"vyper", b"conda"),
    ],
)
def test_internal_assign(get_contract_with_gas_estimation, typ, in_val, out_val):
    code = f"""
@internal
def foo(x: {typ}) -> {typ}:
    x = {out_val}
    return x

@external
def bar(x: {typ}) -> {typ}:
    return self.foo(x)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.bar(in_val) == out_val


def test_internal_assign_struct(get_contract_with_gas_estimation):
    code = """
flag Bar:
    BAD
    BAK
    BAZ

struct Foo:
    a: uint256
    b: DynArray[Bar, 3]
    c: String[5]

@internal
def foo(x: Foo) -> Foo:
    x = Foo(a=789, b=[Bar.BAZ, Bar.BAK, Bar.BAD], c=\"conda\")
    return x

@external
def bar(x: Foo) -> Foo:
    return self.foo(x)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.bar((123, [1, 2, 4], "vyper")) == (789, [4, 2, 1], "conda")


def test_internal_assign_struct_member(get_contract_with_gas_estimation):
    code = """
flag Bar:
    BAD
    BAK
    BAZ

struct Foo:
    a: uint256
    b: DynArray[Bar, 3]
    c: String[5]

@internal
def foo(x: Foo) -> Foo:
    x.a = 789
    x.b.pop()
    return x

@external
def bar(x: Foo) -> Foo:
    return self.foo(x)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.bar((123, [1, 2, 4], "vyper")) == (789, [1, 2], "vyper")


def test_internal_augassign(get_contract_with_gas_estimation):
    code = """
@internal
def foo(x: int128) -> int128:
    x += 77
    return x

@external
def bar(x: int128) -> int128:
    return self.foo(x)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.bar(123) == 200


@pytest.mark.parametrize("typ", ["DynArray[uint256, 3]", "uint256[3]"])
def test_internal_augassign_arrays(get_contract_with_gas_estimation, typ):
    code = f"""
@internal
def foo(x: {typ}) -> {typ}:
    x[1] += 77
    return x

@external
def bar(x: {typ}) -> {typ}:
    return self.foo(x)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.bar([1, 2, 3]) == [1, 79, 3]


def test_invalid_external_assign(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@external
def foo(x: int128):
    x = 5
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), ImmutableViolation)


def test_invalid_external_augassign(assert_compile_failed, get_contract_with_gas_estimation):
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


def test_invalid_uint256_assignment(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
storx: uint256

@external
def foo2() -> uint256:
    x: uint256 = -1
    x += 1
    return x
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatch)


def test_invalid_uint256_assignment_calculate_literals(get_contract_with_gas_estimation):
    code = """
storx: uint256

@external
def foo2() -> uint256:
    x: uint256 = 0
    x = 3 * 4 // 2 + 1 - 2
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
    z: bytes32 = empty(bytes32)
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
    z: bytes32 = empty(bytes32)
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

    # GH issue 2418


overlap_codes = [
    """
@external
def bug(xs: uint256[2]) -> uint256[2]:
    # Initial value
    ys: uint256[2] = xs
    ys = [ys[1], ys[0]]
    return ys
    """,
    """
foo: uint256[2]
@external
def bug(xs: uint256[2]) -> uint256[2]:
    # Initial value
    self.foo = xs
    self.foo = [self.foo[1], self.foo[0]]
    return self.foo
    """,
    # TODO add transient tests when it's available
]


@pytest.mark.parametrize("code", overlap_codes)
def test_assign_rhs_lhs_overlap(get_contract, code):
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
    t = Point(x=t.y, y=t.x)
    return t
    """
    c = get_contract(code)
    assert c.bug((1, 2)) == (2, 1)


mload_merge_codes = [
    (
        """
@external
def foo() -> uint256[4]:
    # copy "backwards"
    xs: uint256[4] = [1, 2, 3, 4]

# dst < src
    xs[0] = xs[1]
    xs[1] = xs[2]
    xs[2] = xs[3]

    return xs
    """,
        [2, 3, 4, 4],
    ),
    (
        """
@external
def foo() -> uint256[4]:
    # copy "forwards"
    xs: uint256[4] = [1, 2, 3, 4]

# src < dst
    xs[1] = xs[0]
    xs[2] = xs[1]
    xs[3] = xs[2]

    return xs
    """,
        [1, 1, 1, 1],
    ),
    (
        """
@external
def foo() -> uint256[5]:
    # partial "forward" copy
    xs: uint256[5] = [1, 2, 3, 4, 5]

# src < dst
    xs[2] = xs[0]
    xs[3] = xs[1]
    xs[4] = xs[2]

    return xs
    """,
        [1, 2, 1, 2, 1],
    ),
]


# functional test that mload merging does not occur when source and dest
# buffers overlap. (note: mload merging only applies after cancun)
@pytest.mark.parametrize("code,expected_result", mload_merge_codes)
def test_mcopy_overlap(get_contract, code, expected_result):
    c = get_contract(code)
    assert c.foo() == expected_result
