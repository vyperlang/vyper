import pytest

from vyper.compiler.settings import OptimizationLevel


@pytest.mark.parametrize(
    "typ,value",
    [
        ("uint256", 42),
        ("int256", -(2**200)),
        ("int128", -(2**126)),
        ("address", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE"),
        ("bytes32", b"deadbeef" * 4),
        ("bool", True),
        ("String[10]", "Vyper hiss"),
        ("Bytes[10]", b"Vyper hiss"),
    ],
)
def test_value_storage_retrieval(typ, value, get_contract):
    code = f"""
VALUE: immutable({typ})

@deploy
def __init__(_value: {typ}):
    VALUE = _value

@view
@external
def get_value() -> {typ}:
    return VALUE
    """

    c = get_contract(code, value)
    assert c.get_value() == value


@pytest.mark.parametrize("val", [0, 1, 2**256 - 1])
def test_usage_in_constructor(get_contract, val):
    code = """
A: immutable(uint256)
a: public(uint256)


@deploy
def __init__(_a: uint256):
    A = _a
    self.a = A


@external
@view
def a1() -> uint256:
    return A
    """

    c = get_contract(code, val)
    assert c.a1() == c.a() == val


def test_multiple_immutable_values(get_contract):
    code = """
a: immutable(uint256)
b: immutable(address)
c: immutable(String[64])

@deploy
def __init__(_a: uint256, _b: address, _c: String[64]):
    a = _a
    b = _b
    c = _c

@view
@external
def get_values() -> (uint256, address, String[64]):
    return a, b, c
    """
    values = (3, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", "Hello world")
    c = get_contract(code, *values)
    assert c.get_values() == list(values)


def test_struct_immutable(get_contract):
    code = """
struct MyStruct:
    a: uint256
    b: uint256
    c: address
    d: int256

my_struct: immutable(MyStruct)

@deploy
def __init__(_a: uint256, _b: uint256, _c: address, _d: int256):
    my_struct = MyStruct(
        a=_a,
        b=_b,
        c=_c,
        d=_d
    )

@view
@external
def get_my_struct() -> MyStruct:
    return my_struct
    """
    values = (100, 42, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", -(2**200))
    c = get_contract(code, *values)
    assert c.get_my_struct() == values


def test_complex_immutable_modifiable(get_contract):
    code = """
struct MyStruct:
    a: uint256

my_struct: immutable(MyStruct)

@deploy
def __init__(a: uint256):
    my_struct = MyStruct(a=a)

    # struct members are modifiable after initialization
    my_struct.a += 1

@view
@external
def get_my_struct() -> MyStruct:
    return my_struct
    """
    c = get_contract(code, 1)
    assert c.get_my_struct() == (2,)


def test_list_immutable(get_contract):
    code = """
my_list: immutable(uint256[3])

@deploy
def __init__(_a: uint256, _b: uint256, _c: uint256):
    my_list = [_a, _b, _c]

@view
@external
def get_my_list() -> uint256[3]:
    return my_list
    """
    values = (100, 42, 23230)
    c = get_contract(code, *values)
    assert c.get_my_list() == list(values)


def test_dynarray_immutable(get_contract):
    code = """
my_list: immutable(DynArray[uint256, 3])

@deploy
def __init__(_a: uint256, _b: uint256, _c: uint256):
    my_list = [_a, _b, _c]

@view
@external
def get_my_list() -> DynArray[uint256, 3]:
    return my_list

@view
@external
def get_idx_two() -> uint256:
    return my_list[2]
    """
    values = (100, 42, 23230)
    c = get_contract(code, *values)
    assert c.get_my_list() == list(values)
    assert c.get_idx_two() == values[2]


def test_nested_dynarray_immutable_2(get_contract):
    code = """
my_list: immutable(DynArray[DynArray[uint256, 3], 3])

@deploy
def __init__(_a: uint256, _b: uint256, _c: uint256):
    my_list = [[_a, _b, _c], [_b, _a, _c], [_c, _b, _a]]

@view
@external
def get_my_list() -> DynArray[DynArray[uint256, 3], 3]:
    return my_list

@view
@external
def get_idx_two() -> uint256:
    return my_list[2][2]
    """
    values = (100, 42, 23230)
    expected_values = [[100, 42, 23230], [42, 100, 23230], [23230, 42, 100]]
    c = get_contract(code, *values)
    assert c.get_my_list() == expected_values
    assert c.get_idx_two() == expected_values[2][2]


def test_nested_dynarray_immutable(get_contract):
    code = """
my_list: immutable(DynArray[DynArray[DynArray[int128, 3], 3], 3])

@deploy
def __init__(x: int128, y: int128, z: int128):
    my_list = [
        [[x, y, z], [y, z, x], [z, y, x]],
        [
            [x * 1000 + y, y * 1000 + z, z * 1000 + x],
            [- (x * 1000 + y), - (y * 1000 + z), - (z * 1000 + x)],
            [- (x * 1000) + y, - (y * 1000) + z, - (z * 1000) + x],
        ],
        [
            [z * 2, y * 3, x * 4],
            [z * (-2), y * (-3), x * (-4)],
            [z * (-y), y * (-x), x * (-z)],
        ],
    ]

@view
@external
def get_my_list() -> DynArray[DynArray[DynArray[int128, 3], 3], 3]:
    return my_list

@view
@external
def get_idx_two() -> int128:
    return my_list[2][2][2]
    """
    values = (37, 41, 73)
    expected_values = [
        [[37, 41, 73], [41, 73, 37], [73, 41, 37]],
        [[37041, 41073, 73037], [-37041, -41073, -73037], [-36959, -40927, -72963]],
        [[146, 123, 148], [-146, -123, -148], [-2993, -1517, -2701]],
    ]
    c = get_contract(code, *values)
    assert c.get_my_list() == expected_values
    assert c.get_idx_two() == expected_values[2][2][2]


@pytest.mark.parametrize("n", range(5))
def test_internal_function_with_immutables(get_contract, n):
    code = """
@internal
def foo() -> uint256:
    self.counter += 1
    return self.counter

counter: uint256
VALUE: immutable(uint256)

@deploy
def __init__(x: uint256):
    self.counter = x
    self.foo()
    VALUE = self.foo()
    self.foo()

@external
def get_immutable() -> uint256:
    return VALUE
    """

    c = get_contract(code, n)
    assert c.get_immutable() == n + 2


# GH issue 3101
def test_immutables_initialized(get_contract):
    dummy_code = """
@external
def foo() -> uint256:
    return 1
    """
    dummy_contract = get_contract(dummy_code)

    code = """
a: public(immutable(uint256))
b: public(uint256)

@payable
@deploy
def __init__(to_copy: address):
    c: address = create_copy_of(to_copy)
    self.b = a
    a = 12
    """
    c = get_contract(code, dummy_contract.address)

    assert c.b() == 0


# GH issue 3101, take 2
def test_immutables_initialized2(get_contract, get_contract_from_ir):
    dummy_contract = get_contract_from_ir(
        ["deploy", 0, ["seq"] + ["invalid"] * 600, 0], optimize=OptimizationLevel.NONE
    )

    # rekt because immutables section extends past allocated memory
    code = """
a0: immutable(uint256[10])
a: public(immutable(uint256))
b: public(uint256)

@payable
@deploy
def __init__(to_copy: address):
    c: address = create_copy_of(to_copy)
    self.b = a
    a = 12
    a0 = empty(uint256[10])
    """
    c = get_contract(code, dummy_contract.address)

    assert c.b() == 0


# GH issue 3292
def test_internal_functions_called_by_ctor_location(get_contract):
    code = """
d: uint256
x: immutable(uint256)

@deploy
def __init__():
    self.d = 1
    x = 2
    self.a()

@external
def test() -> uint256:
    return self.d

@internal
def a():
    self.d = x
    """
    c = get_contract(code)
    assert c.test() == 2


# GH issue 3292, extended to nested internal functions
def test_nested_internal_function_immutables(get_contract):
    code = """
d: public(uint256)
x: public(immutable(uint256))

@deploy
def __init__():
    self.d = 1
    x = 2
    self.a()

@internal
def a():
    self.b()

@internal
def b():
    self.d = x
    """
    c = get_contract(code)
    assert c.x() == 2
    assert c.d() == 2


# GH issue 3292, test immutable read from both ctor and runtime
def test_immutable_read_ctor_and_runtime(get_contract):
    code = """
d: public(uint256)
x: public(immutable(uint256))

@deploy
def __init__():
    self.d = 1
    x = 2
    self.a()

@internal
def a():
    self.d = x

@external
def thrash():
    self.d += 5

@external
def fix():
    self.a()
    """
    c = get_contract(code)
    assert c.x() == 2
    assert c.d() == 2

    c.thrash(transact={})

    assert c.x() == 2
    assert c.d() == 2 + 5

    c.fix(transact={})
    assert c.x() == 2
    assert c.d() == 2
