import pytest

from tests.utils import ZERO_ADDRESS
from vyper.compiler import compile_code
from vyper.exceptions import EvmVersionException, VyperException

pytestmark = pytest.mark.requires_evm_version("cancun")


def test_transient_compiles():
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
    "typ,value,zero",
    [
        ("uint256", 42, 0),
        ("int256", -(2**200), 0),
        ("int128", -(2**126), 0),
        ("address", "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", ZERO_ADDRESS),
        ("bytes32", b"deadbeef" * 4, b"\x00" * 32),
        ("bool", True, False),
        ("String[10]", "Vyper hiss", ""),
        ("Bytes[10]", b"Vyper hiss", b""),
    ],
)
def test_value_storage_retrieval(typ, value, zero, get_contract, env):
    code = f"""
bar: public(transient({typ}))

@external
def foo(a: {typ}) -> {typ}:
    self.bar = a
    return self.bar
    """

    c = get_contract(code)
    assert c.bar() == zero
    assert c.foo(value) == value
    env.clear_transient_storage()

    assert c.bar() == zero
    assert c.foo(value) == value
    env.clear_transient_storage()

    assert c.bar() == zero


@pytest.mark.parametrize("val", [0, 1, 2**256 - 1])
def test_usage_in_constructor(get_contract, val, env):
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
    assert c.a() == val
    env.clear_transient_storage()

    assert c.a1() == 0


def test_multiple_transient_values(get_contract, env):
    code = """
a: public(transient(uint256))
b: public(transient(address))
c: public(transient(String[64]))

@external
def foo(_a: uint256, _b: address, _c: String[64]) -> (uint256, address, String[64]):
    self.a = _a
    self.b = _b
    self.c = _c
    return self.a, self.b, self.c
    """

    try:
        compile_code(code)
    except VyperException as e:
        assert e.message.count("EvmVersionException") == 3
        # raise EvmVersionException to satisfy `requires_evm_version` behavior
        raise EvmVersionException()

    values = (3, "0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", "Hello world")
    c = get_contract(code)
    assert c.foo(*values) == values
    env.clear_transient_storage()

    assert c.a() == 0
    assert c.b() == ZERO_ADDRESS
    assert c.c() == ""
    assert c.foo(*values) == values


def test_struct_transient(get_contract, env):
    code = """
struct MyStruct:
    a: uint256
    b: uint256
    c: address
    d: int256

my_struct: public(transient(MyStruct))

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
    assert c.foo(*values) == values
    env.clear_transient_storage()

    assert c.my_struct() == (0, 0, ZERO_ADDRESS, 0)
    assert c.foo(*values) == values


def test_complex_struct_transient(get_contract, env):
    code = """
struct MyStruct:
    a: address
    b: MyStruct2
    c: DynArray[DynArray[uint256, 3], 3]

struct MyStruct2:
    a: DynArray[uint256, 3]

my_struct: public(transient(MyStruct))

@external
def foo(_a: address, _b: MyStruct2, _c: DynArray[DynArray[uint256, 3], 3]) -> MyStruct:
    self.my_struct = MyStruct(
        a=_a,
        b=_b,
        c=_c,
    )
    return self.my_struct
    """
    values = ("0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE", ([1],), [[3, 4], [5, 6]])

    c = get_contract(code)
    assert c.foo(*values) == values
    env.clear_transient_storage()

    assert c.my_struct() == (ZERO_ADDRESS, ([],), [])
    assert c.foo(*values) == values


def test_complex_transient_modifiable(get_contract, env):
    code = """
struct MyStruct:
    a: uint256

my_struct: public(transient(MyStruct))

@external
def foo(a: uint256) -> MyStruct:
    self.my_struct = MyStruct(a=a)

    # struct members are modifiable after initialization
    self.my_struct.a += 1

    return self.my_struct
    """

    c = get_contract(code)
    assert c.foo(1) == (2,)
    env.clear_transient_storage()

    assert c.my_struct() == (0,)
    assert c.foo(1) == (2,)


def test_list_transient(get_contract, env):
    code = """
my_list: public(transient(uint256[3]))

@external
def foo(_a: uint256, _b: uint256, _c: uint256) -> uint256[3]:
    self.my_list = [_a, _b, _c]
    return self.my_list
    """
    values = (100, 42, 23230)

    c = get_contract(code)
    assert c.foo(*values) == list(values)
    env.clear_transient_storage()

    for i in range(3):
        assert c.my_list(i) == 0
    assert c.foo(*values) == list(values)


def test_hashmap_transient(get_contract, env):
    code = """
my_map: public(transient(HashMap[uint256, uint256]))

@external
def foo(k: uint256, v: uint256) -> uint256:
    self.my_map[k] = v
    return self.my_map[k]
    """
    c = get_contract(code)
    for v in range(5):
        for k in range(5):
            assert c.foo(k, v) == v
            env.clear_transient_storage()
            assert c.my_map(k) == 0


def test_complex_hashmap_transient(get_contract, env):
    code = """
struct MyStruct:
    a: uint256
    b: DynArray[uint256, 3]

my_map: public(transient(HashMap[uint256, MyStruct]))
my_res: public(HashMap[uint256, MyStruct])

@external
def do_side_effects():
    a: DynArray[uint256, 3] = [1, 2, 3]
    s: MyStruct = MyStruct(a=100, b=a)
    for i: uint256 in range(2):
        for j: uint256 in range(3):
            s.b[j] = i + j
        s.a = i
        self.my_map[i] = s
        self.my_res[i] = self.my_map[i]
    """
    c = get_contract(code)
    c.do_side_effects()
    for i in range(2):
        assert c.my_res(i)[0] == i
        assert c.my_map(i)[0] == 0
        env.clear_transient_storage()

        for j in range(3):
            assert c.my_res(i)[1][j] == i + j
            assert c.my_map(i)[1] == []


def test_dynarray_transient(get_contract, tx_failed, env):
    code = """
my_list: public(transient(DynArray[uint256, 3]))

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
    assert c.get_my_list(*values) == list(values)
    env.clear_transient_storage()

    with tx_failed():
        c.my_list(0)
    assert c.get_idx_two(*values) == values[2]
    env.clear_transient_storage()

    with tx_failed():
        c.my_list(0)


def test_nested_dynarray_transient_2(get_contract):
    code = """
my_list: public(transient(DynArray[DynArray[uint256, 3], 3]))

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
    assert c.get_my_list(*values) == expected_values
    assert c.get_idx_two(*values) == expected_values[2][2]


def test_nested_dynarray_transient(get_contract, tx_failed, env):
    set_list = """
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
    """
    code = f"""
interface Iface:
    def my_list(x: uint256, y: uint256, z: uint256) -> int128: view

my_list: public(transient(DynArray[DynArray[DynArray[int128, 3], 3], 3]))

@external
def get_my_list(x: int128, y: int128, z: int128) -> DynArray[DynArray[DynArray[int128, 3], 3], 3]:
    {set_list}
    return self.my_list

@external
def get_idx_two(x: int128, y: int128, z: int128) -> int128:
    {set_list}
    return self.my_list[2][2][2]

@external
def get_idx_two_using_getter(x: int128, y: int128, z: int128) -> int128:
    {set_list}
    return staticcall Iface(self).my_list(2, 2, 2)
    """
    values = (37, 41, 73)
    expected_values = [
        [[37, 41, 73], [41, 73, 37], [73, 41, 37]],
        [[37041, 41073, 73037], [-37041, -41073, -73037], [-36959, -40927, -72963]],
        [[146, 123, 148], [-146, -123, -148], [-2993, -1517, -2701]],
    ]

    c = get_contract(code)
    assert c.get_my_list(*values) == expected_values
    env.clear_transient_storage()

    with tx_failed():
        c.my_list(0, 0, 0)
    assert c.get_idx_two(*values) == expected_values[2][2][2]
    env.clear_transient_storage()

    with tx_failed():
        c.my_list(0, 0, 0)
    assert c.get_idx_two_using_getter(*values) == expected_values[2][2][2]
    env.clear_transient_storage()

    with tx_failed():
        c.my_list(0, 0, 0)


@pytest.mark.parametrize("n", range(5))
def test_internal_function_with_transient(get_contract, n, env):
    code = """
@internal
def foo() -> uint256:
    self.counter += 1
    return self.counter

counter: uint256
val: public(transient(uint256))

@external
def bar(x: uint256) -> uint256:
    self.counter = x
    self.foo()
    self.val = self.foo()
    return self.val
    """

    c = get_contract(code)
    assert c.bar(n) == n + 2
    env.clear_transient_storage()

    assert c.val() == 0
    assert c.bar(n) == n + 2


def test_nested_internal_function_transient(get_contract, env):
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
    assert c.d() == 2
    env.clear_transient_storage()

    assert c.x() == 0


def test_view_function_transient(get_contract, env):
    c1 = """
x: transient(uint256)

@external
def set_x(i: uint256):
    self.x = i

@external
@view
def get_x() -> uint256:
    return self.x
    """

    c2 = """
interface Foo:
    def set_x(i: uint256): nonpayable
    def get_x() -> uint256: view

@external
def bar(i: uint256, a: address) -> uint256:
    f: Foo = Foo(a)
    extcall f.set_x(i)
    return staticcall f.get_x()
    """

    c1 = get_contract(c1)
    c2 = get_contract(c2)

    value = 333
    assert c2.bar(value, c1.address) == value
    env.clear_transient_storage()

    assert c1.get_x() == 0


def test_modules_transient(get_contract, make_input_bundle):
    lib1 = """
counter: transient(uint256)
    """
    lib2 = """
import lib1

uses: lib1

counter: transient(uint256)
counter2: public(uint256)

@internal
def foo():
    lib1.counter += 1
    """
    main = """
import lib2
import lib1

initializes: lib2[lib1 := lib1]
initializes: lib1

@external
def foo() -> (uint256, uint256):
    lib1.counter = 2
    lib2.foo()
    lib2.counter = 10
    return lib1.counter, lib2.counter
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == (3, 10)


def test_complex_modules_transient(get_contract, make_input_bundle):
    lib1 = """
l: transient(uint256[3])
    """
    lib2 = """
import lib1

uses: lib1

struct MyStruct:
    a: uint256
    b: uint256

s: transient(MyStruct)

@internal
def foo():
    self.s = MyStruct(a=lib1.l[0], b=lib1.l[1])
    """
    main = """
import lib2
import lib1

initializes: lib2[lib1 := lib1]
initializes: lib1

my_map: HashMap[uint256, uint256]

@external
def foo() -> (uint256[3], uint256, uint256, uint256):
    lib1.l = [1, 2, 3]
    lib2.foo()
    self.my_map[0] = 42
    return lib1.l, lib2.s.a, lib2.s.b, self.my_map[0]
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    c = get_contract(main, input_bundle=input_bundle)
    assert c.foo() == ([1, 2, 3], 1, 2, 42)
