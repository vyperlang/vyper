import pytest

from vyper.exceptions import ArgumentException

_fun_bytes32_bounds = [(0, 32), (3, 29), (27, 5), (0, 5), (5, 3), (30, 2)]


def _generate_bytes(length):
    return bytes(list(range(length)))


# good numbers to try
_fun_numbers = [0, 1, 5, 31, 32, 33, 64, 99, 100, 101]


# [b"", b"\x01", b"\x02"...]
_bytes_examples = [_generate_bytes(i) for i in _fun_numbers if i <= 100]


def test_basic_slice(get_contract_with_gas_estimation):
    code = """
@external
def slice_tower_test(inp1: Bytes[50]) -> Bytes[50]:
    inp: Bytes[50] = inp1
    for i in range(1, 11):
        inp = slice(inp, 1, 30 - i * 2)
    return inp
    """
    c = get_contract_with_gas_estimation(code)
    x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"klmnopqrst", x


@pytest.mark.parametrize("bytesdata", _bytes_examples)
@pytest.mark.parametrize("start", _fun_numbers)
@pytest.mark.parametrize("literal_start", (True, False))
@pytest.mark.parametrize("length", _fun_numbers)
@pytest.mark.parametrize("literal_length", (True, False))
@pytest.mark.fuzzing
def test_slice_immutable(
    get_contract,
    assert_compile_failed,
    assert_tx_failed,
    bytesdata,
    start,
    literal_start,
    length,
    literal_length,
):
    _start = start if literal_start else "start"
    _length = length if literal_length else "length"

    code = f"""
IMMUTABLE_BYTES: immutable(Bytes[100])
IMMUTABLE_SLICE: immutable(Bytes[100])

@external
def __init__(inp: Bytes[100], start: uint256, length: uint256):
    IMMUTABLE_BYTES = inp
    IMMUTABLE_SLICE = slice(IMMUTABLE_BYTES, {_start}, {_length})

@external
def do_splice() -> Bytes[100]:
    return IMMUTABLE_SLICE
    """

    if (
        (start + length > 100 and literal_start and literal_length)
        or (literal_length and length > 100)
        or (literal_start and start > 100)
        or (literal_length and length < 1)
    ):
        assert_compile_failed(
            lambda: get_contract(code, bytesdata, start, length), ArgumentException
        )
    elif start + length > len(bytesdata):
        assert_tx_failed(lambda: get_contract(code, bytesdata, start, length))
    else:
        c = get_contract(code, bytesdata, start, length)
        assert c.do_splice() == bytesdata[start : start + length]


@pytest.mark.parametrize("location", ("storage", "calldata", "memory", "literal", "code"))
@pytest.mark.parametrize("bytesdata", _bytes_examples)
@pytest.mark.parametrize("start", _fun_numbers)
@pytest.mark.parametrize("literal_start", (True, False))
@pytest.mark.parametrize("length", _fun_numbers)
@pytest.mark.parametrize("literal_length", (True, False))
@pytest.mark.fuzzing
def test_slice_bytes(
    get_contract,
    assert_compile_failed,
    assert_tx_failed,
    location,
    bytesdata,
    start,
    literal_start,
    length,
    literal_length,
):
    if location == "memory":
        spliced_code = "foo: Bytes[100] = inp"
        foo = "foo"
    elif location == "storage":
        spliced_code = "self.foo = inp"
        foo = "self.foo"
    elif location == "code":
        spliced_code = ""
        foo = "IMMUTABLE_BYTES"
    elif location == "literal":
        spliced_code = ""
        foo = f"{bytesdata}"
    elif location == "calldata":
        spliced_code = ""
        foo = "inp"
    else:
        raise Exception("unreachable")

    _start = start if literal_start else "start"
    _length = length if literal_length else "length"

    code = f"""
foo: Bytes[100]
IMMUTABLE_BYTES: immutable(Bytes[100])
@external
def __init__(foo: Bytes[100]):
    IMMUTABLE_BYTES = foo

@external
def do_slice(inp: Bytes[100], start: uint256, length: uint256) -> Bytes[100]:
    {spliced_code}
    return slice({foo}, {_start}, {_length})
    """

    length_bound = len(bytesdata) if location == "literal" else 100
    if (
        (start + length > length_bound and literal_start and literal_length)
        or (literal_length and length > length_bound)
        or (literal_start and start > length_bound)
        or (literal_length and length < 1)
    ):
        assert_compile_failed(lambda: get_contract(code, bytesdata), ArgumentException)
    elif start + length > len(bytesdata):
        c = get_contract(code, bytesdata)
        assert_tx_failed(lambda: c.do_slice(bytesdata, start, length))
    else:
        c = get_contract(code, bytesdata)
        assert c.do_slice(bytesdata, start, length) == bytesdata[start : start + length], code


def test_slice_private(get_contract):
    # test there are no buffer overruns in the slice function
    code = """
bytez: public(String[12])

@internal
def _slice(start: uint256, length: uint256):
    self.bytez = slice(self.bytez, start, length)

@external
def foo(x: uint256, y: uint256) -> (uint256, String[12]):
    self.bytez = "hello, world"
    dont_clobber_me: uint256 = max_value(uint256)
    self._slice(x, y)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    assert c.foo(0, 12) == [2**256 - 1, "hello, world"]
    assert c.foo(12, 0) == [2**256 - 1, ""]
    assert c.foo(7, 5) == [2**256 - 1, "world"]
    assert c.foo(0, 5) == [2**256 - 1, "hello"]
    assert c.foo(0, 1) == [2**256 - 1, "h"]
    assert c.foo(11, 1) == [2**256 - 1, "d"]


def test_slice_storage_bytes32(get_contract):
    code = """
bytez: bytes32
@external
def dice() -> Bytes[1]:
    self.bytez = convert(65, bytes32)
    c: Bytes[1] = slice(self.bytez, 31, 1)
    return c
    """

    c = get_contract(code)
    assert c.dice() == b"A"


def test_slice_immutable_length_arg(get_contract_with_gas_estimation):
    code = """
LENGTH: immutable(uint256)

@external
def __init__():
    LENGTH = 5

@external
def do_slice(inp: Bytes[50]) -> Bytes[50]:
    return slice(inp, 0, LENGTH)
    """
    c = get_contract_with_gas_estimation(code)
    x = c.do_slice(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"abcde", x


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


def test_slice_expr(get_contract):
    # test slice of a complex expression
    code = """
@external
def ret10_slice() -> Bytes[10]:
    return slice(convert(65, bytes32), 31, 1)
    """

    c = get_contract(code)
    assert c.ret10_slice() == b"A"


def test_slice_equality(get_contract):
    # test for equality with dirty bytes
    code = """
@external
def assert_eq() -> bool:
    dirty_bytes: String[4] = "abcd"
    dirty_bytes = slice(dirty_bytes, 0, 3)
    clean_bytes: String[4] = "abc"
    return dirty_bytes == clean_bytes
    """

    c = get_contract(code)
    assert c.assert_eq()


def test_slice_inequality(get_contract):
    # test for equality with dirty bytes
    code = """
@external
def assert_ne() -> bool:
    dirty_bytes: String[4] = "abcd"
    dirty_bytes = slice(dirty_bytes, 0, 3)
    clean_bytes: String[4] = "abcd"
    return dirty_bytes != clean_bytes
    """

    c = get_contract(code)
    assert c.assert_ne()


def test_slice_convert(get_contract):
    # test slice of converting between bytes32 and Bytes
    code = """
@external
def f() -> bytes32:
    a: Bytes[100] = convert("ab", Bytes[100])
    return convert(slice(a, 0, 1), bytes32)
    """
    c = get_contract(code)
    assert c.f() == b"a" + b"\x00" * 31


code_bytes32 = [
    """
foo: bytes32

@external
def __init__():
    self.foo = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f

@external
def bar() -> Bytes[{length}]:
    return slice(self.foo, {start}, {length})
    """,
    """
foo: bytes32

@external
def __init__():
    self.foo = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f

@external
def bar() -> Bytes[32]:
    a: uint256 = {start}
    b: uint256 = {length}
    return slice(self.foo, a, b)
    """,
    f"""
foo: Bytes[32]

@external
def bar() -> Bytes[32]:
    self.foo = {_generate_bytes(32)}
    a: uint256 = {{start}}
    b: uint256 = {{length}}
    return slice(convert(self.foo, bytes32), a, b)
    """,
    """
@external
def bar() -> Bytes[{length}]:
    foo: bytes32 = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
    return slice(foo, {start}, {length})
    """,
    """
@external
def bar() -> Bytes[32]:
    b: uint256 = {length}
    foo: bytes32 = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f
    a: uint256 = {start}
    return slice(foo, a, b)
    """,
]


@pytest.mark.parametrize("code", code_bytes32)
@pytest.mark.parametrize("start,length", _fun_bytes32_bounds)
def test_slice_bytes32(get_contract, code, start, length):
    c = get_contract(code.format(start=start, length=length))
    assert c.bar() == _generate_bytes(32)[start : start + length]


code_bytes32_calldata = [
    """
@external
def bar(foo: bytes32) -> Bytes[{length}]:
    return slice(foo, {start}, {length})
    """,
    """
@external
def bar(foo: bytes32) -> Bytes[32]:
    b: uint256 = {length}
    a: uint256 = {start}
    return slice(foo, a, b)
    """,
]


@pytest.mark.parametrize("code", code_bytes32_calldata)
@pytest.mark.parametrize("start,length", _fun_bytes32_bounds)
def test_slice_bytes32_calldata(get_contract, code, start, length):
    c = get_contract(code.format(start=start, length=length))
    assert c.bar(_generate_bytes(32)) == _generate_bytes(32)[start : start + length]


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
