import pytest

from vyper.compiler import compile_code
from vyper.evm.opcodes import version_check
from vyper.exceptions import TransientStorageException, VyperException


def test_transient_blocked(get_contract):
    # test transient is blocked on pre-cancun and compiles post-cancun
    code = """
my_map: transient(HashMap[address, uint256])
    """
    get_contract(code)


def test_transient_compiles():
    if not version_check(begin="cancun"):
        pytest.skip("transient storage will not compile, pre-cancun")

    getter_code = """
my_map: public(transient(HashMap[address, uint256]))
    """
    t = compile_code(getter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" not in t

    setter_code = """
my_map: transient(HashMap[address, uint256])

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(setter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" not in t
    assert "TSTORE" in t

    getter_setter_code = """
my_map: public(transient(HashMap[address, uint256]))

@external
def setter(k: address, v: uint256):
    self.my_map[k] = v
    """
    t = compile_code(getter_setter_code, output_formats=["opcodes_runtime"])
    t = t["opcodes_runtime"].split(" ")

    assert "TLOAD" in t
    assert "TSTORE" in t


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
bar: transient({typ})

@external
def foo(a: {typ}) -> {typ}:
    self.bar = a
    return self.bar
    """

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.foo(value) == value


@pytest.mark.parametrize("val", [0, 1, 2**256 - 1])
def test_usage_in_constructor(get_contract, val):
    code = """
A: transient(uint256)
a: public(uint256)


@deploy
def __init__(_a: uint256):
    self.A = _a
    self.a = self.A


@external
@view
def a1() -> uint256:
    return self.A
    """

    c = get_contract(code, val)
    if version_check(begin="cancun"):
        assert c.a() == val
        assert c.a1() == 0


def test_multiple_transient_values(get_contract):
    code = """
a: transient(uint256)
b: transient(address)
c: transient(String[64])

@external
def foo(_a: uint256, _b: address, _c: String[64]) -> (uint256, address, String[64]):
    self.a = _a
    self.b = _b
    self.c = _c
    return self.a, self.b, self.c
    """
    values = (3, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", "Hello world")

    if version_check(begin="cancun"):
        c = get_contract(code)
        assert c.foo(*values) == list(values)
    else:
        # multiple errors
        with pytest.raises(VyperException):
            compile_code(code)


def test_struct_transient(get_contract):
    code = """
struct MyStruct:
    a: uint256
    b: uint256
    c: address
    d: int256

my_struct: transient(MyStruct)

@external
def foo(_a: uint256, _b: uint256, _c: address, _d: int256) -> MyStruct:
    self.my_struct = MyStruct(
        a=_a,
        b=_b,
        c=_c,
        d=_d
    )
    return self.my_struct
    """
    values = (100, 42, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", -(2**200))

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.foo(*values) == values


def test_complex_transient_modifiable(get_contract):
    code = """
struct MyStruct:
    a: uint256

my_struct: transient(MyStruct)

@external
def foo(a: uint256) -> MyStruct:
    self.my_struct = MyStruct(a=a)

    # struct members are modifiable after initialization
    self.my_struct.a += 1

    return self.my_struct
    """

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.foo(1) == (2,)


def test_list_transient(get_contract):
    code = """
my_list: transient(uint256[3])

@external
def foo(_a: uint256, _b: uint256, _c: uint256) -> uint256[3]:
    self.my_list = [_a, _b, _c]
    return self.my_list
    """
    values = (100, 42, 23230)

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.foo(*values) == list(values)


def test_dynarray_transient(get_contract):
    code = """
my_list: transient(DynArray[uint256, 3])

@external
def get_my_list(_a: uint256, _b: uint256, _c: uint256) -> DynArray[uint256, 3]:
    self.my_list = [_a, _b, _c]
    return self.my_list

@external
def get_idx_two(_a: uint256, _b: uint256, _c: uint256) -> uint256:
    self.my_list = [_a, _b, _c]
    return self.my_list[2]
    """
    values = (100, 42, 23230)

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.get_my_list(*values) == list(values)
        assert c.get_idx_two(*values) == values[2]


def test_nested_dynarray_transient_2(get_contract):
    code = """
my_list: transient(DynArray[DynArray[uint256, 3], 3])

@external
def get_my_list(_a: uint256, _b: uint256, _c: uint256) -> DynArray[DynArray[uint256, 3], 3]:
    self.my_list = [[_a, _b, _c], [_b, _a, _c], [_c, _b, _a]]
    return self.my_list

@external
def get_idx_two(_a: uint256, _b: uint256, _c: uint256) -> uint256:
    self.my_list = [[_a, _b, _c], [_b, _a, _c], [_c, _b, _a]]
    return self.my_list[2][2]
    """
    values = (100, 42, 23230)
    expected_values = [[100, 42, 23230], [42, 100, 23230], [23230, 42, 100]]

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.get_my_list(*values) == expected_values
        assert c.get_idx_two(*values) == expected_values[2][2]


def test_nested_dynarray_transient(get_contract):
    code = """
my_list: transient(DynArray[DynArray[DynArray[int128, 3], 3], 3])

@external
def get_my_list(x: int128, y: int128, z: int128) -> DynArray[DynArray[DynArray[int128, 3], 3], 3]:
    self.my_list = [
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
    return self.my_list

@external
def get_idx_two(x: int128, y: int128, z: int128) -> int128:
    self.my_list = [
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
    return self.my_list[2][2][2]
    """
    values = (37, 41, 73)
    expected_values = [
        [[37, 41, 73], [41, 73, 37], [73, 41, 37]],
        [[37041, 41073, 73037], [-37041, -41073, -73037], [-36959, -40927, -72963]],
        [[146, 123, 148], [-146, -123, -148], [-2993, -1517, -2701]],
    ]

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.get_my_list(*values) == expected_values
        assert c.get_idx_two(*values) == expected_values[2][2][2]


@pytest.mark.parametrize("n", range(5))
def test_internal_function_with_transient(get_contract, n):
    code = """
@internal
def foo() -> uint256:
    self.counter += 1
    return self.counter

counter: uint256
val: transient(uint256)

@external
def bar(x: uint256) -> uint256:
    self.counter = x
    self.foo()
    self.val = self.foo()
    return self.val
    """

    c = get_contract(code)
    if version_check(begin="cancun"):
        assert c.bar(n) == n + 2


def test_nested_internal_function_transient(get_contract):
    code = """
d: public(uint256)
x: public(transient(uint256))

@deploy
def __init__():
    self.d = 1
    self.x = 2
    self.a()

@internal
def a():
    self.b()

@internal
def b():
    self.d = self.x
    """

    c = get_contract(code)

    if version_check(begin="cancun"):
        assert c.d() == 2
