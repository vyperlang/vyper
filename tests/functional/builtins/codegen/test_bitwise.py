import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from vyper.compiler import compile_code
from vyper.exceptions import InvalidLiteral, InvalidOperation, TypeMismatch, UnimplementedException
from vyper.utils import unsigned_to_signed


def get_code_for_type(typ, use_shift=True):
    code = f"""
@external
def _bitwise_and(x: {typ}, y: {typ}) -> {typ}:
    return x & y
@external
def _bitwise_or(x: {typ}, y: {typ}) -> {typ}:
    return x | y
@external
def _bitwise_xor(x: {typ}, y: {typ}) -> {typ}:
    return x ^ y
@external
def _bitwise_not(x: {typ}) -> {typ}:
    return ~x
    """

    shift_code = f"""
@external
def _shl(x: {typ}, y: uint256) -> {typ}:
    return x << y
@external
def _shr(x: {typ}, y: uint256) -> {typ}:
    return x >> y
    """
    if use_shift:
        return code + shift_code

    return code


BYTESM_TYPES = ["bytes" + str(i + 1) for i in range(32)]
UINT_TYPES = ["uint" + str(i + 8) for i in range(0, 256, 8)]
ALL_TYPES = BYTESM_TYPES + UINT_TYPES


@pytest.mark.parametrize("typ", ["uint256", "bytes32"])
def test_bitwise_opcodes(typ):
    code = get_code_for_type(typ)
    opcodes = compile_code(code, output_formats=["opcodes"])["opcodes"]
    assert "SHL" in opcodes
    assert "SHR" in opcodes


@pytest.mark.parametrize("typ", ["uint256", "bytes32"])
@pytest.mark.xfail  # fails due to bad vyper grammar
def test_not_roundtrip(get_contract, typ):
    code = f"""
@external
def round_trip() -> {typ}:
        b: {typ} = empty({typ})
        return ~~b
    """
    c = get_contract(code)
    assert c.round_trip() == (0 if typ == "uint256" else b"\00" * 32)


@pytest.mark.parametrize("typ", [typ for typ in ALL_TYPES if typ not in ["uint256", "bytes32"]])
@pytest.mark.parametrize("shift_op", ["<<", ">>"])
def test_invalid_shift(typ, shift_op):
    code = f"""
@external
def do_shift(x: {typ}, y: uint256) -> {typ}:
    return x {shift_op} y
    """
    with pytest.raises(InvalidOperation):
        compile_code(code)


@pytest.mark.parametrize("typ", [typ for typ in ALL_TYPES if typ not in ["uint256", "bytes32"]])
def test_unimplemented_unary_not(typ):
    code = f"""
@external
def do_not(x: {typ}) -> {typ}:
    return ~x
    """
    with pytest.raises(UnimplementedException):
        compile_code(code)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(value=st.binary(min_size=32, max_size=32))
def test_not_operator_bytes(get_contract, value):
    source = """
@external
def foo(a: bytes32) -> bytes32:
    return ~a
     """
    contract = get_contract(source)

    foo_res = contract.foo(value)

    expected = bytes(~b & 0xFF for b in value)

    assert foo_res == expected


@st.composite
def get_bytes(draw, len):
    return draw(
        st.tuples(st.binary(min_size=len, max_size=len), st.binary(min_size=len, max_size=len))
    )


@pytest.mark.fuzzing
@pytest.mark.parametrize("typ", BYTESM_TYPES)
@pytest.mark.parametrize("op", ["&", "|", "^"])
def test_bitwise_binary_bytes(get_contract, typ, op):
    source = f"""
@external
def do_op(a: {typ}, b: {typ}) -> {typ}:
    return a {op} b
     """
    contract = get_contract(source)
    bytes_len = int(typ.removeprefix("bytes"))

    @given(values=get_bytes(bytes_len))
    @settings(max_examples=50)
    def _fuzz(values):
        val1, val2 = values
        res = contract.do_op(val1, val2)
        if op == "&":
            expected = bytes(x & y for x, y in zip(val1, val2))
        elif op == "|":
            expected = bytes(x | y for x, y in zip(val1, val2))
        else:
            assert op == "^"
            expected = bytes(x ^ y for x, y in zip(val1, val2))

        assert res == expected

    _fuzz()


@pytest.mark.fuzzing
@pytest.mark.parametrize("op", ["<<", ">>"])
def test_bitwise_shift_bytes(get_contract, op):
    source = f"""
@external
def do_op(a: bytes32, b: uint256) -> bytes32:
   return a {op} b
        """
    contract = get_contract(source)

    @given(
        bytes_value=st.binary(min_size=32, max_size=32),
        shift_by=st.integers(min_value=0, max_value=257),
    )
    @settings(max_examples=10000)
    def _fuzz(bytes_value, shift_by):
        res = contract.do_op(bytes_value, shift_by)
        if op == ">>":
            expected = int.from_bytes(bytes_value, "big")
            expected = expected >> shift_by
            expected = expected.to_bytes(32, "big")
        else:
            assert op == "<<"
            expected = int.from_bytes(bytes_value, "big")
            mask = (1 << 256) - 1
            expected = (expected << shift_by) & mask
            expected = expected.to_bytes(32, "big")

        assert res == expected

    _fuzz()


def test_test_bitwise(get_contract):
    code = get_code_for_type("uint256")
    c = get_contract(code)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    assert c._bitwise_and(x, y) == (x & y)
    assert c._bitwise_or(x, y) == (x | y)
    assert c._bitwise_xor(x, y) == (x ^ y)
    assert c._bitwise_not(x) == 2**256 - 1 - x

    for t in (x, y):
        for s in (0, 1, 3, 255, 256):
            assert c._shr(t, s) == t >> s
            assert c._shl(t, s) == (t << s) % (2**256)


def test_signed_shift(get_contract):
    code = """
@external
def _sar(x: int256, y: uint256) -> int256:
    return x >> y

@external
def _shl(x: int256, y: uint256) -> int256:
    return x << y
    """
    c = get_contract(code)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    cases = [x, y, -x, -y]

    for t in cases:
        for s in (0, 1, 3, 255, 256):
            assert c._sar(t, s) == t >> s
            assert c._shl(t, s) == unsigned_to_signed((t << s) % (2**256), 256)


def test_precedence(get_contract):
    code = """
@external
def foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a | b & c, (a | b) & c)

@external
def bar(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a | ~b & c, (a | ~b) & c)

@external
def baz(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a + 8 | ~b & c * 2, (a  + 8 | ~b) & c * 2)
    """
    c = get_contract(code)
    assert tuple(c.foo(1, 6, 14)) == (1 | 6 & 14, (1 | 6) & 14) == (7, 6)
    assert tuple(c.bar(1, 6, 14)) == (1 | ~6 & 14, (1 | ~6) & 14) == (9, 8)
    assert tuple(c.baz(1, 6, 14)) == (1 + 8 | ~6 & 14 * 2, (1 + 8 | ~6) & 14 * 2) == (25, 24)


def test_literals(get_contract):
    code = """
@external
def _shr(x: uint256) -> uint256:
    return x >> 3

@external
def _shl(x: uint256) -> uint256:
    return x << 3
    """

    c = get_contract(code)
    assert c._shr(80) == 10
    assert c._shl(80) == 640


fail_list = [
    (
        # cannot shift by non-uint bits
        """
def foo(a: bytes32, b: int256) -> bytes32:
    return a << b
    """,
        TypeMismatch,
    ),
    (
        # cannot shift non-uint256/int256 argument
        """
@external
def foo(x: uint8, y: uint8) -> uint8:
    return x << y
    """,
        InvalidOperation,
    ),
    (
        # cannot shift non-uint256/int256 argument
        """
@external
def foo(x: int8, y: uint8) -> int8:
    return x << y
    """,
        InvalidOperation,
    ),
    (
        # cannot shift by non-uint bits
        """
@external
def foo(x: uint256, y: int128) -> uint256:
    return x << y
    """,
        TypeMismatch,
    ),
    (
        # cannot left shift by more than 256 bits
        """
@external
def foo() -> uint256:
    return 2 << 257
    """,
        InvalidLiteral,
    ),
    (
        # cannot shift by negative amount
        """
@external
def foo() -> uint256:
    return 2 << -1
    """,
        InvalidLiteral,
    ),
    (
        # cannot shift by negative amount
        """
@external
def foo() -> uint256:
    return 2 << -1
    """,
        InvalidLiteral,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_shift_fail(get_contract, bad_code, exc, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), exc)
