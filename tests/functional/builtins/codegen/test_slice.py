import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.evm.opcodes import version_check
from vyper.exceptions import ArgumentException, TypeMismatch

_fun_bytes32_bounds = [(0, 32), (3, 29), (27, 5), (0, 5), (5, 3), (30, 2)]


def _generate_bytes(length):
    return bytes(list(range(length)))


def test_basic_slice(get_contract):
    code = """
@external
def slice_tower_test(inp1: Bytes[50]) -> Bytes[50]:
    inp: Bytes[50] = inp1
    for i: uint256 in range(1, 11):
        inp = slice(inp, 1, 30 - i * 2)
    return inp
    """
    c = get_contract(code)
    x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"klmnopqrst", x


# note: optimization boundaries at 32, 64 and 320 depending on mode
_draw_1024 = st.integers(min_value=0, max_value=1024)
_draw_1024_1 = st.integers(min_value=1, max_value=1024)
_bytes_1024 = st.binary(min_size=0, max_size=1024)


def _fail_contract(code, opt_level, exceptions):
    settings = Settings(optimize=opt_level)
    with pytest.raises(exceptions):
        compile_code(code, settings)


@pytest.mark.parametrize("use_literal_start", (True, False))
@pytest.mark.parametrize("use_literal_length", (True, False))
@pytest.mark.parametrize("opt_level", list(OptimizationLevel))
@given(start=_draw_1024, length=_draw_1024, length_bound=_draw_1024_1, bytesdata=_bytes_1024)
@settings(max_examples=100)
@pytest.mark.fuzzing
def test_slice_immutable(
    get_contract,
    tx_failed,
    opt_level,
    bytesdata,
    start,
    use_literal_start,
    length,
    use_literal_length,
    length_bound,
):
    _start = start if use_literal_start else "start"
    _length = length if use_literal_length else "length"

    code = f"""
IMMUTABLE_BYTES: immutable(Bytes[{length_bound}])
IMMUTABLE_SLICE: immutable(Bytes[{length_bound}])

@deploy
def __init__(inp: Bytes[{length_bound}], start: uint256, length: uint256):
    IMMUTABLE_BYTES = inp
    IMMUTABLE_SLICE = slice(IMMUTABLE_BYTES, {_start}, {_length})

@external
def do_splice() -> Bytes[{length_bound}]:
    return IMMUTABLE_SLICE
    """

    def _get_contract():
        return get_contract(code, bytesdata, start, length, override_opt_level=opt_level)

    if (
        (start + length > length_bound and use_literal_start and use_literal_length)
        or (use_literal_length and length > length_bound)
        or (use_literal_start and start > length_bound)
        or (use_literal_length and length == 0)
    ):
        _fail_contract(code, opt_level, ArgumentException)

    elif start + length > len(bytesdata) or (len(bytesdata) > length_bound):
        # deploy fail
        with tx_failed():
            _get_contract()
    else:
        c = _get_contract()
        assert c.do_splice() == bytesdata[start : start + length]


@pytest.mark.parametrize(
    "location", ["storage", "transient", "calldata", "memory", "literal", "code"]
)
@pytest.mark.parametrize("use_literal_start", (True, False))
@pytest.mark.parametrize("use_literal_length", (True, False))
@pytest.mark.parametrize("opt_level", list(OptimizationLevel))
@given(start=_draw_1024, length=_draw_1024, length_bound=_draw_1024_1, bytesdata=_bytes_1024)
@settings(max_examples=100)
@pytest.mark.fuzzing
def test_slice_bytes_fuzz(
    get_contract,
    tx_failed,
    opt_level,
    location,
    bytesdata,
    start,
    use_literal_start,
    length,
    use_literal_length,
    length_bound,
):
    if location == "transient" and not version_check(begin="cancun"):
        pytest.skip(
            "Skipping test as storage_location is 'transient' and EVM version is pre-Cancun"
        )
    preamble = ""
    if location == "memory":
        spliced_code = f"foo: Bytes[{length_bound}] = inp"
        foo = "foo"
    elif location == "storage":
        preamble = f"""
foo: Bytes[{length_bound}]
         """
        spliced_code = "self.foo = inp"
        foo = "self.foo"
    elif location == "transient":
        preamble = f"""
foo: transient(Bytes[{length_bound}])
        """
        spliced_code = "self.foo = inp"
        foo = "self.foo"
    elif location == "code":
        preamble = f"""
IMMUTABLE_BYTES: immutable(Bytes[{length_bound}])
@deploy
def __init__(foo: Bytes[{length_bound}]):
    IMMUTABLE_BYTES = foo
    """
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

    _start = start if use_literal_start else "start"
    _length = length if use_literal_length else "length"

    code = f"""
{preamble}

@external
def do_slice(inp: Bytes[{length_bound}], start: uint256, length: uint256) -> Bytes[{length_bound}]:
    {spliced_code}
    return slice({foo}, {_start}, {_length})
    """

    def _get_contract():
        if "__init__" in code:
            # eth-tester used to ignore constructor arguments if no constructor was defined
            # now we raise an exception, so only call the constructor if it exists
            # TODO: Refactor so we don't rely on searching the source code.
            return get_contract(code, bytesdata, override_opt_level=opt_level)
        return get_contract(code, override_opt_level=opt_level)

    # length bound is the container size; input_bound is the bound on the input
    # (which can be different, if the input is a literal)
    input_bound = length_bound
    slice_output_too_large = False

    if location == "literal":
        input_bound = len(bytesdata)

        # ex.:
        # @external
        # def do_slice(inp: Bytes[1], start: uint256, length: uint256) -> Bytes[1]:
        #    return slice(b'\x00\x00', 0, length)
        output_length = length if use_literal_length else input_bound
        slice_output_too_large = output_length > length_bound

    end = start + length

    compile_time_oob = (
        (use_literal_length and (length > input_bound or length == 0))
        or (use_literal_start and start > input_bound)
        or (use_literal_start and use_literal_length and start + length > input_bound)
    )

    if compile_time_oob or slice_output_too_large:
        _fail_contract(code, opt_level, (ArgumentException, TypeMismatch))

    elif location == "code" and len(bytesdata) > length_bound:
        # deploy fail
        with tx_failed():
            _get_contract()
    elif end > len(bytesdata) or len(bytesdata) > length_bound:
        c = _get_contract()
        with tx_failed():
            c.do_slice(bytesdata, start, length)
    else:
        c = _get_contract()
        assert c.do_slice(bytesdata, start, length) == bytesdata[start:end], code


@pytest.mark.parametrize("location", ["storage", "transient"])
def test_slice_private(get_contract, location):
    if location == "transient" and not version_check(begin="cancun"):
        pytest.skip(
            "Skipping test as storage_location is 'transient' and EVM version is pre-Cancun"
        )

    # test there are no buffer overruns in the slice function
    if location == "storage":
        decl = "bytez: public(String[12])"
    elif location == "transient":
        decl = "bytez: public(transient(String[12]))"
    else:
        raise Exception("unreachable")

    code = f"""
{decl}

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
    assert c.foo(0, 12) == (2**256 - 1, "hello, world")
    assert c.foo(12, 0) == (2**256 - 1, "")
    assert c.foo(7, 5) == (2**256 - 1, "world")
    assert c.foo(0, 5) == (2**256 - 1, "hello")
    assert c.foo(0, 1) == (2**256 - 1, "h")
    assert c.foo(11, 1) == (2**256 - 1, "d")


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


def test_slice_immutable_length_arg(get_contract):
    code = """
LENGTH: immutable(uint256)

@deploy
def __init__():
    LENGTH = 5

@external
def do_slice(inp: Bytes[50]) -> Bytes[50]:
    return slice(inp, 0, LENGTH)
    """
    c = get_contract(code)
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

@deploy
def __init__():
    self.foo = 0x000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f

@external
def bar() -> Bytes[{length}]:
    return slice(self.foo, {start}, {length})
    """,
    """
foo: bytes32

@deploy
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


# test cases crafted based on advisory GHSA-9x7f-gwxq-6f2c
oob_fail_list = [
    """
d: public(Bytes[256])

@external
def do_slice():
    x : uint256 = max_value(uint256)
    self.d = b"\x01\x02\x03\x04\x05\x06"
    assert len(slice(self.d, 1, x)) == max_value(uint256)
    """,
    """
@external
def do_slice():
    x: uint256 = max_value(uint256)
    # y == 0x3232323232323232323232323232323232323232323232323232323232323232
    y: uint256 = 22704331223003175573249212746801550559464702875615796870481879217237868556850
    z: uint96 = 1
    if True:
        placeholder : uint256[16] = [y, y, y, y, y, y, y, y, y, y, y, y, y, y, y, y]
    s: String[32] = slice(uint2str(z), 1, x)
    assert slice(s, 1, 2) == "22"
    """,
    """
x: public(Bytes[64])
secret: uint256

@deploy
def __init__():
    self.x = empty(Bytes[64])
    self.secret = 42

@external
def do_slice() -> Bytes[64]:
    start: uint256 = max_value(uint256) - 63
    return slice(self.x, start, 64)
    """,
    # tests bounds check in adhoc location calldata
    """
interface IFace:
    def choose_value(_x: uint256, _y: uint256, _z: uint256, idx: uint256) -> Bytes[32]: nonpayable

@external
def choose_value(_x: uint256, _y: uint256, _z: uint256, idx: uint256) -> Bytes[32]:
    assert idx % 32 == 4
    return slice(msg.data, idx, 32)

@external
def do_slice():
    idx: uint256 = max_value(uint256) - 27
    ret: uint256 = _abi_decode(extcall IFace(self).choose_value(1, 2, 3, idx), uint256)
    assert ret == 0
    """,
]


@pytest.mark.parametrize("bad_code", oob_fail_list)
def test_slice_buffer_oob_reverts(bad_code, get_contract, tx_failed):
    c = get_contract(bad_code)
    with tx_failed():
        c.do_slice()
