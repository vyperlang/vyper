import pytest

from vyper.exceptions import InstantiationException, TypeMismatch


@pytest.mark.parametrize(
    "contract",
    [
        """
foobar: int128

@external
def foo():
    self.foobar = 1
    bar: int128 = 1

    self.foobar = empty(int128)
    bar = empty(int128)

    assert self.foobar == 0
    assert bar == 0
    """,
        """
foobar: uint256

@external
def foo():
    self.foobar = 1
    bar: uint256 = 1

    self.foobar = empty(uint256)
    bar = empty(uint256)

    assert self.foobar == 0
    assert bar == 0
    """,
        """
foobar: bool

@external
def foo():
    self.foobar = True
    bar: bool = True

    self.foobar = empty(bool)
    bar = empty(bool)

    assert self.foobar == False
    assert bar == False
    """,
        """
foobar: decimal

@external
def foo():
    self.foobar = 1.0
    bar: decimal = 1.0

    self.foobar = empty(decimal)
    bar = empty(decimal)

    assert self.foobar == 0.0
    assert bar == 0.0
    """,
        """
foobar: bytes32

@external
def foo():
    self.foobar = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    bar: bytes32 = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF

    self.foobar = empty(bytes32)
    bar = empty(bytes32)

    assert self.foobar == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar == 0x0000000000000000000000000000000000000000000000000000000000000000
    """,
        """
foobar: address

@external
def foo():
    self.foobar = msg.sender
    bar: address = msg.sender

    self.foobar = empty(address)
    bar = empty(address)

    assert self.foobar == empty(address)
    assert bar == empty(address)
    """,
        """
@external
def foo() -> bool:
    return empty(bool)
    """,
    ],
)
def test_empty_basic_type(contract, get_contract_with_gas_estimation):
    c = get_contract_with_gas_estimation(contract)
    c.foo()


@pytest.mark.parametrize(
    "contract",
    [
        """
foobar: int128[3]

@external
def foo():
    self.foobar = [1, 2, 3]
    bar: int128[3] = [1, 2, 3]

    self.foobar = empty(int128[3])
    bar = empty(int128[3])

    assert self.foobar[0] == 0
    assert self.foobar[1] == 0
    assert self.foobar[2] == 0
    assert bar[0] == 0
    assert bar[1] == 0
    assert bar[2] == 0
    """,
        """
foobar: uint256[3]

@external
def foo():
    self.foobar = [1, 2, 3]
    bar: uint256[3] = [1, 2, 3]

    self.foobar = empty(uint256[3])
    bar = empty(uint256[3])

    assert self.foobar[0] == 0
    assert self.foobar[1] == 0
    assert self.foobar[2] == 0
    assert bar[0] == 0
    assert bar[1] == 0
    assert bar[2] == 0
    """,
        """
foobar: bool[3]

@external
def foo():
    self.foobar = [True, True, True]
    bar: bool[3] = [True, True, True]

    self.foobar = empty(bool[3])
    bar = empty(bool[3])

    assert self.foobar[0] == False
    assert self.foobar[1] == False
    assert self.foobar[2] == False
    assert bar[0] == False
    assert bar[1] == False
    assert bar[2] == False
    """,
        """
foobar: decimal[3]

@external
def foo():
    self.foobar = [1.0, 2.0, 3.0]
    bar: decimal[3] = [1.0, 2.0, 3.0]

    self.foobar = empty(decimal[3])
    bar = empty(decimal[3])

    assert self.foobar[0] == 0.0
    assert self.foobar[1] == 0.0
    assert self.foobar[2] == 0.0
    assert bar[0] == 0.0
    assert bar[1] == 0.0
    assert bar[2] == 0.0
    """,
        """
foobar: bytes32[3]

@external
def foo():
    self.foobar = [
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000000000000000000000000000,
        0x00000000000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    ]
    bar: bytes32[3] = [
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000000000000000000000000000,
        0x00000000000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    ]

    self.foobar = empty(bytes32[3])
    bar = empty(bytes32[3])

    assert self.foobar[0] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar[1] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar[2] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[0] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[1] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[2] == 0x0000000000000000000000000000000000000000000000000000000000000000
    """,
        """
foobar: address[3]

@external
def foo():
    self.foobar = [msg.sender, msg.sender, msg.sender]
    bar: address[3] = [msg.sender, msg.sender, msg.sender]

    self.foobar = empty(address[3])
    bar = empty(address[3])

    assert self.foobar[0] == empty(address)
    assert self.foobar[1] == empty(address)
    assert self.foobar[2] == empty(address)
    assert bar[0] == empty(address)
    assert bar[1] == empty(address)
    assert bar[2] == empty(address)
    """,
    ],
)
def test_empty_basic_type_lists(contract, get_contract_with_gas_estimation):
    c = get_contract_with_gas_estimation(contract)
    c.foo()


@pytest.mark.parametrize(
    "contract",
    [
        """
@external
def foo() -> uint256:
    return empty(1)
    """,
        """
@external
def foo() -> decimal:
    return empty(1.0)
    """,
        """
@external
def foo() -> bytes32:
    return empty(0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)
    """,
        """
@external
def foo() -> address:
    return empty(0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7)
    """,
        """
@external
def foo():
    x: uint256 = 1
    empty(x)
    """,
    ],
)
def test_clear_literals(contract, assert_compile_failed, get_contract_with_gas_estimation):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), Exception)


def test_empty_bytes(get_contract_with_gas_estimation):
    code = """
foobar: Bytes[5]

@external
def foo() -> (Bytes[5], Bytes[5]):
    self.foobar = b'Hello'
    bar: Bytes[5] = b'World'

    self.foobar = empty(Bytes[5])
    bar = empty(Bytes[5])

    return (self.foobar, bar)
    """

    c = get_contract_with_gas_estimation(code)
    a, b = c.foo()
    assert a == b == b""


@pytest.mark.parametrize(
    "length,value,result",
    [
        (1, "a", False),
        (1, "", True),
        (8, "helloooo", False),
        (8, "hello", False),
        (8, "", True),
        (40, "a", False),
        (40, "hellohellohellohellohellohellohellohello", False),
        (40, "", True),
    ],
)
@pytest.mark.parametrize("op", ["==", "!="])
def test_empty_string_comparison(get_contract_with_gas_estimation, length, value, result, op):
    contract = f"""
@external
def foo(xs: String[{length}]) -> bool:
    return xs {op} empty(String[{length}])
    """
    c = get_contract_with_gas_estimation(contract)
    if op == "==":
        assert c.foo(value) == result
    elif op == "!=":
        assert c.foo(value) != result


@pytest.mark.parametrize(
    "length,value,result",
    [
        (1, b"a", False),
        (1, b"", True),
        (8, b"helloooo", False),
        (8, b"hello", False),
        (8, b"", True),
        (40, b"a", False),
        (40, b"hellohellohellohellohellohellohellohello", False),
        (40, b"", True),
    ],
)
@pytest.mark.parametrize("op", ["==", "!="])
def test_empty_bytes_comparison(get_contract_with_gas_estimation, length, value, result, op):
    contract = f"""
@external
def foo(xs: Bytes[{length}]) -> bool:
    return empty(Bytes[{length}]) {op} xs
    """
    c = get_contract_with_gas_estimation(contract)
    if op == "==":
        assert c.foo(value) == result
    elif op == "!=":
        assert c.foo(value) != result


def test_empty_struct(get_contract_with_gas_estimation):
    code = """
struct FOOBAR:
    a: int128
    b: uint256
    c: bool
    d: decimal
    e: bytes32
    f: address

foobar: FOOBAR

@external
def foo():
    self.foobar = FOOBAR(
        a=1,
        b=2,
        c=True,
        d=3.0,
        e=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        f=msg.sender
    )
    bar: FOOBAR = FOOBAR(
        a=1,
        b=2,
        c=True,
        d=3.0,
        e=0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        f=msg.sender
    )

    self.foobar = empty(FOOBAR)
    bar = empty(FOOBAR)

    assert self.foobar.a == 0
    assert self.foobar.b == 0
    assert self.foobar.c == False
    assert self.foobar.d == 0.0
    assert self.foobar.e == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar.f == empty(address)

    assert bar.a == 0
    assert bar.b == 0
    assert bar.c == False
    assert bar.d == 0.0
    assert bar.e == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar.f == empty(address)
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()


def test_empty_dynarray(get_contract_with_gas_estimation):
    code = """
foobar: DynArray[uint256, 10]
bar: uint256

@external
def foo():
    self.bar = 1
    self.foobar = [1,2,3,4,5]
    assert len(self.foobar) == 5

    self.foobar = empty(DynArray[uint256, 10])

    assert len(self.foobar) == 0
    assert self.bar == 1
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()


# param empty not working yet
@pytest.mark.xfail
def test_param_empty(get_contract_with_gas_estimation):
    code = """
interface Mirror:
    # reuse the contract for this test by compiling two copies of it
    def test_empty(xs: int128[111], ys: Bytes[1024], zs: Bytes[31]) -> bool: view

# a helper function which will write all over memory with random stuff
@internal
def write_junk_to_memory():
    xs: int128[1024] = empty(int128[1024])
    for i: uint256 in range(1024):
        xs[i] = -(i + 1)
@internal
def priv(xs: int128[111], ys: Bytes[1024], zs: Bytes[31]) -> bool:
    return xs[1] == 0 and ys == b'' and zs == b''

@external
def test_empty(xs: int128[111], ys: Bytes[1024], zs: Bytes[31]) -> bool:
    empty_bytes1024: Bytes[1024] = empty(Bytes[1024])
    empty_bytes31: Bytes[31] = empty(Bytes[31])
    self.write_junk_to_memory()
    # no list equality yet so test some sample values
    return xs[0] == 0 and xs[110] == 0 and ys == empty_bytes1024 and zs == empty_bytes31

@external
def pub2() -> bool:
    self.write_junk_to_memory()
    return self.priv(empty(int128[111]), empty(Bytes[1024]), empty(Bytes[31]))

@external
def pub3(x: address) -> bool:
    self.write_junk_to_memory()
    return staticcall Mirror(x).test_empty(empty(int128[111]), empty(Bytes[1024]), empty(Bytes[31]))
    """
    c = get_contract_with_gas_estimation(code)
    mirror = get_contract_with_gas_estimation(code)

    assert c.test_empty([0] * 111, b"", b"")
    assert c.pub2()
    assert c.pub3(mirror.address)


# return empty not working yet
@pytest.mark.xfail
def test_return_empty(get_contract_with_gas_estimation):
    code = """
struct X:
    foo: int128
    bar: address
    baz: decimal
    qux: int128[1]

# a helper function which will write all over memory with random stuff
@internal
def write_junk_to_memory():
    xs: int128[1024] = empty(int128[1024])
    for i: uint256 in range(1024):
        xs[i] = -(i + 1)

@external
def a() -> uint256:
    self.write_junk_to_memory()
    return empty(uint256)

@external
def b() -> uint256[5]:
    self.write_junk_to_memory()
    return empty(uint256[5])

@external
def c() -> uint256[5][5]:
    self.write_junk_to_memory()
    return empty(uint256[5][5])

@external
def d() -> Bytes[55]:
    self.write_junk_to_memory()
    return empty(Bytes[55])

@external
def e() -> X:
    self.write_junk_to_memory()
    return empty(X)
    """
    c = get_contract_with_gas_estimation(code)

    assert c.a() == 0
    assert c.b() == [0] * 5
    assert c.c() == [[0] * 5] * 5
    assert c.d() == b""
    assert c.e() == (0, "0x" + "0" * 40, 0x0, [0])


def test_map_clear(get_contract_with_gas_estimation):
    code = """
big_storage: HashMap[bytes32, bytes32]

@external
def set(key: bytes32, _value: bytes32):
    self.big_storage[key] = _value

@external
def get(key: bytes32) -> bytes32:
    return self.big_storage[key]

@external
def delete(key: bytes32):
    self.big_storage[key] = empty(bytes32)
    """

    c = get_contract_with_gas_estimation(code)

    key = b"test".ljust(32)
    val = b"value".ljust(32)

    assert c.get(key) == b"\x00" * 32
    c.set(key, val, transact={})
    assert c.get(key)[:5] == b"value"
    c.delete(key, transact={})
    assert c.get(key) == b"\x00" * 32


def test_map_clear_nested(get_contract_with_gas_estimation):
    code = """
big_storage: HashMap[bytes32, HashMap[bytes32, bytes32]]

@external
def set(key1: bytes32, key2: bytes32, _value: bytes32):
    self.big_storage[key1][key2] = _value

@external
def get(key1: bytes32, key2: bytes32) -> bytes32:
    return self.big_storage[key1][key2]

@external
def delete(key1: bytes32, key2: bytes32):
    self.big_storage[key1][key2] = empty(bytes32)
    """

    c = get_contract_with_gas_estimation(code)

    key1 = b"test1".ljust(32)
    key2 = b"test2".ljust(32)
    val = b"value".ljust(32)

    assert c.get(key1, key2) == b"\x00" * 32
    c.set(key1, key2, val, transact={})
    assert c.get(key1, key2)[:5] == b"value"
    c.delete(key1, key2, transact={})
    assert c.get(key1, key2) == b"\x00" * 32


def test_map_clear_struct(get_contract_with_gas_estimation):
    code = """
struct X:
    a: int128
    b: int128

structmap: HashMap[int128, X]

@external
def set():
    self.structmap[123] = X(a=333, b=444)

@external
def get() -> (int128, int128):
    return self.structmap[123].a, self.structmap[123].b

@external
def delete():
    self.structmap[123] = empty(X)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.get() == [0, 0]
    c.set(transact={})
    assert c.get() == [333, 444]
    c.delete(transact={})
    assert c.get() == [0, 0]


@pytest.mark.parametrize(
    "contract",
    [
        """
@external
def foo():
    xs: uint256[10] = empty(uint256[11])
    """,
        """
@external
def bar():
    ys: Bytes[33] = empty(Bytes[32])
    """,
        """
@external
def baz():
    zs: decimal[1][1] = empty(address[1][1])
    """,
    ],
)
def test_clear_typecheck(contract, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(contract), TypeMismatch)


@pytest.mark.parametrize(
    "a,b,expected",
    [
        ("empty(Bytes[65])", "b'hello'", [b"hello", b""]),
        ("b'hello'", "empty(Bytes[33])", [b"", b"hello"]),
        (
            "empty(Bytes[65])",
            "b'thirty three bytes long baby!!!!!'",
            [b"thirty three bytes long baby!!!!!", b""],
        ),
        (
            "b'thirty three bytes long baby!!!aathirty three bytes long baby!!!a'",
            "b'thirty three bytes long baby!!!aa'",
            [
                b"thirty three bytes long baby!!!aa",
                b"thirty three bytes long baby!!!aathirty three bytes long baby!!!a",
            ],
        ),
    ],
)
def test_empty_as_func_arg(get_contract, a, b, expected):
    code_a = """
@view
@external
def foo(
    a: uint256, b: Bytes[65], c: uint256, d: Bytes[33]
) -> (uint256, Bytes[33], Bytes[65], uint256):
    return a, d, b, c
    """

    code_b = f"""
interface Foo:
    def foo(
        a: uint256, b: Bytes[65], c: uint256, d: Bytes[33]
    ) -> (uint256, Bytes[33], Bytes[65], uint256): view

@view
@external
def bar(a: address) -> (uint256, Bytes[33], Bytes[65], uint256):
    return staticcall Foo(a).foo(12, {a}, 42, {b})
    """

    c1 = get_contract(code_a)
    c2 = get_contract(code_b)

    assert c2.bar(c1.address) == [12] + expected + [42]


def test_empty_array_in_event_logging(get_contract, get_logs):
    code = """
event MyLog:
    arg1: Bytes[64]
    arg2: int128[2][3]
    arg3: int128
    arg4: Bytes[64]
    arg5: uint256[3]

@external
def foo():
    log MyLog(
        b'hellohellohellohellohellohellohellohellohello',
        empty(int128[2][3]),
        314159,
        b'helphelphelphelphelphelphelphelphelphelphelp',
        empty(uint256[3])
    )
    """

    c = get_contract(code)
    log = get_logs(c.foo(transact={}), c, "MyLog")[0]

    assert log.args.arg1 == b"hello" * 9
    assert log.args.arg2 == [[0, 0], [0, 0], [0, 0]]
    assert log.args.arg3 == 314159
    assert log.args.arg4 == b"help" * 11
    assert log.args.arg5 == [0, 0, 0]


@pytest.mark.parametrize(
    "contract",
    [
        """
@external
def test():
    a: uint256 = empty(HashMap[uint256, uint256])[0]
    """
    ],
)
def test_invalid_types(contract, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(contract), InstantiationException)
