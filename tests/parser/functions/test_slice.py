import pytest


def test_test_slice(get_contract_with_gas_estimation):
    test_slice = """

@external
def foo(inp1: Bytes[10]) -> Bytes[3]:
    x: int128 = 5
    s: Bytes[3] = slice(inp1, 3, 3)
    y: int128 = 7
    return s

@external
def bar(inp1: Bytes[10]) -> int128:
    x: int128 = 5
    s: Bytes[3] = slice(inp1, 3, 3)
    y: int128 = 7
    return x * y
    """

    c = get_contract_with_gas_estimation(test_slice)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35


def test_test_slice2(get_contract_with_gas_estimation):
    test_slice2 = """
@external
def slice_tower_test(inp1: Bytes[50]) -> Bytes[50]:
    inp: Bytes[50] = inp1
    for i in range(1, 11):
        inp = slice(inp, 1, 30 - i * 2)
    return inp
    """
    c = get_contract_with_gas_estimation(test_slice2)
    x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"klmnopqrst", x


def test_test_slice3(get_contract_with_gas_estimation):
    test_slice3 = """
x: int128
s: Bytes[50]
y: int128
@external
def foo(inp1: Bytes[50]) -> Bytes[50]:
    self.x = 5
    self.s = slice(inp1, 3, 3)
    self.y = 7
    return self.s

@external
def bar(inp1: Bytes[50]) -> int128:
    self.x = 5
    self.s = slice(inp1,3, 3)
    self.y = 7
    return self.x * self.y
    """

    c = get_contract_with_gas_estimation(test_slice3)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35


def test_test_slice4(get_contract_with_gas_estimation, assert_tx_failed):
    test_slice4 = """
@external
def foo(inp: Bytes[10], start: uint256, _len: uint256) -> Bytes[10]:
    return slice(inp, start, _len)
    """

    c = get_contract_with_gas_estimation(test_slice4)
    assert c.foo(b"badminton", 3, 3) == b"min"
    assert c.foo(b"badminton", 0, 9) == b"badminton"
    assert c.foo(b"badminton", 1, 8) == b"adminton"
    assert c.foo(b"badminton", 1, 7) == b"adminto"
    assert c.foo(b"badminton", 1, 0) == b""
    assert c.foo(b"badminton", 9, 0) == b""

    assert_tx_failed(lambda: c.foo(b"badminton", 0, 10))
    assert_tx_failed(lambda: c.foo(b"badminton", 1, 9))
    assert_tx_failed(lambda: c.foo(b"badminton", 9, 1))
    assert_tx_failed(lambda: c.foo(b"badminton", 10, 0))


def test_slice_at_end(get_contract):
    code = """
@external
def ret10_slice() -> Bytes[10]:
    b: Bytes[32] = concat(convert(65, bytes32), b'')
    c: Bytes[10] = slice(b, 31, 1)
    return c
    """

    c = get_contract(code)
    assert c.ret10_slice() == b"A"


code_bytes32 = [
    """
foo: bytes32

@external
def __init__():
    self.foo = 0x0001020304050607080910111213141516171819202122232425262728293031

@external
def bar() -> Bytes[5]:
    return slice(self.foo, 3, 5)
    """,
    """
foo: bytes32

@external
def __init__():
    self.foo = 0x0001020304050607080910111213141516171819202122232425262728293031

@external
def bar() -> Bytes[32]:
    a: uint256 = 3
    b: uint256 = 5
    return slice(self.foo, a, b)
    """,
    """
@external
def bar() -> Bytes[5]:
    foo: bytes32 = 0x0001020304050607080910111213141516171819202122232425262728293031
    return slice(foo, 3, 5)
    """,
    """
@external
def bar() -> Bytes[32]:
    b: uint256 = 5
    foo: bytes32 = 0x0001020304050607080910111213141516171819202122232425262728293031
    a: uint256 = 3
    return slice(foo, a, b)
    """,
]


@pytest.mark.parametrize("code", code_bytes32)
def test_slice_bytes32(get_contract, code):

    c = get_contract(code)
    assert c.bar().hex() == "0304050607"


code_bytes32_calldata = [
    """
@external
def bar(foo: bytes32) -> Bytes[32]:
    return slice(foo, 3, 5)
    """,
    """
@external
def bar(foo: bytes32) -> Bytes[32]:
    b: uint256 = 5
    a: uint256 = 3
    return slice(foo, a, b)
    """,
]


@pytest.mark.parametrize("code", code_bytes32_calldata)
def test_slice_bytes32_calldata(get_contract, code):

    c = get_contract(code)
    assert (
        c.bar("0x0001020304050607080910111213141516171819202122232425262728293031").hex()
        == "0304050607"
    )


code_bytes32_calldata_extended = [
    (
        """
@external
def bar(a: uint256, foo: bytes32, b: uint256) -> Bytes[32]:
    return slice(foo, 3, 5)
    """,
        "0304050607",
    ),
    (
        """
@external
def bar(a: uint256, foo: bytes32, b: uint256) -> Bytes[32]:
    return slice(foo, a, b)
    """,
        "0304050607",
    ),
    (
        """
@external
def bar(a: uint256, foo: bytes32, b: uint256) -> Bytes[32]:
    return slice(foo, 31, b-4)
    """,
        "31",
    ),
    (
        """
@external
def bar(a: uint256, foo: bytes32, b: uint256) -> Bytes[32]:
    return slice(foo, 0, a+b)
    """,
        "0001020304050607",
    ),
]


@pytest.mark.parametrize("code,result", code_bytes32_calldata_extended)
def test_slice_bytes32_calldata_extended(get_contract, code, result):

    c = get_contract(code)
    assert (
        c.bar(3, "0x0001020304050607080910111213141516171819202122232425262728293031", 5).hex()
        == result
    )
