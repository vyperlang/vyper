from decimal import Decimal
import itertools
from typing import Any
import random
from dataclasses import dataclass

import pytest
from eth_abi import decode_single, encode_single
import eth_abi.exceptions

from vyper.codegen.types import (
    BASE_TYPES,
    INTEGER_TYPES,
    parse_bytes_m_info,
    parse_decimal_info,
    parse_integer_typeinfo,
)
from vyper.exceptions import InvalidLiteral, InvalidType, OverflowException, TypeMismatch
from vyper.utils import (
    DECIMAL_DIVISOR,
    SizeLimits,
    bytes_to_int,
    checksum_encode,
    hex_to_int,
    int_bounds,
    unsigned_to_signed,
    round_towards_zero,
)
import enum

ADDRESS_BITS = 160

TEST_TYPES = BASE_TYPES | {"Bytes[32]"}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ONE_ADDRESS = "0x0000000000000000000000000000000000000001"
MAX_ADDRESS = "0xFFfFfFffFFfffFFfFFfFFFFFffFFFffffFfFFFfF"

# decimal increment, aka smallest decimal > 0
DECIMAL_EPSILON = Decimal(1) / DECIMAL_DIVISOR


@dataclass
class TestType:
    """
    Simple class to model Vyper types.
    """

    type_name: str
    type_bytes: int  # number of nonzero bytes this type can take
    type_class: str  # e.g. int, uint, String, decimal
    type_info: Any  # e.g. DecimalInfo

    @property
    def abi_type(self):
        if self.type_name == "decimal":
            return "fixed168x10"
        if self.type_class in ("Bytes", "String"):
            return self.type_name.lower()
        return self.type_name


class _OutOfBounds(Exception):
    """
    A Python-level conversion is out of bounds
    """

    pass


def _parse_type(typename):
    if typename.startswith("uint") or typename.startswith("int"):
        info = parse_integer_typeinfo(typename)
        assert info.m_bits % 8 == 0
        return TestType(typename, info.m_bits // 8, "int", info)
    elif typename == "decimal":
        info = parse_decimal_info(typename)
        assert info.m_bits % 8 == 0
        return TestType(typename, info.m_bits // 8, "decimal", info)
    elif typename.startswith("bytes"):
        info = parse_bytes_m_info(typename)
        return TestType(typename, info.m, "bytes", info)
    elif typename.startswith("Bytes"):
        assert typename == "Bytes[32]"  # TODO test others
        return TestType(typename, 32, "Bytes", info)
    elif typename.startswith("String"):
        assert typename == "String[32]"  # TODO test others
        return TestType(typename, 32, "Bytes", info)


def can_convert(i_typ, o_typ):
    """
    Checks whether conversion from one type to another is valid.
    """
    i_detail = _parse_type(i_typ)
    o_detail = _parse_type(o_typ)

    if i_typ == "bool" or o_typ == "bool":
        return True

    if i_detail.type_class == "int":
        ret = o_detail.type_class in ("int", "decimal", "bytes", "Bytes")
        if not i_typ.info.is_signed:
            ret |= o_typ == "address"
        return ret

    elif i_detail.type_class == "bytes":
        if o_detail.type_class in ("int", "Bytes", "address"):
            # bytesN must be of equal or larger size to [u]intM
            return i_detail.type_bytes <= o_detail.type_bytes

        elif i_detail.type_class == "decimal":
            return True  # this may be an inconsistency in the spec.

    elif i_detail.type_class == "Bytes":
        return o_detail.type_class in ("int", "decimal", "address")

    elif i_typ == "decimal":
        return o_detail.type_class in ("int", "bytes", "bool")

    elif i_typ == "address":
        return o_typ in ("uint", "bytes")

    raise AssertionError("unreachable")


def uniq(xs):
    return list(set(xs))


def _cases_for_int(typ):
    info = parse_integer_typeinfo(typ)

    lo, hi = info.bounds

    ret = [lo - 1, lo, lo + 1, -1, 0, 1, hi - 1, hi, hi + 1]

    NUM_RANDOM_CASES = 6
    ret.extend(random.randrange(lo, hi) for _ in range(NUM_RANDOM_CASES))

    return ret


def _cases_for_decimal(typ):
    info = parse_decimal_info(typ)

    lo, hi = info.decimal_bounds
    DIVISOR = info.divisor

    ret = [lo - 1, lo, lo + 1, -1, 0, 1, hi - 1, hi, hi + 1]

    ret.extend(
        [lo - DECIMAL_EPSILON, lo + DECIMAL_EPSILON, hi - DECIMAL_EPSILON, hi + DECIMAL_EPSILON]
    )

    # use int values because randrange can't generate fractional decimals
    int_lo, int_hi = info.bounds  # e.g. -(2**167)
    NUM_RANDOM_CASES = 10  # more than int, just for paranoia's sake
    ret.extend(random.randrange(int_lo, int_hi) / DIVISOR for _ in range(NUM_RANDOM_CASES))

    return ret


def _cases_for_address(_typ):
    cases = _filter_cases(_cases_for_int("uint160"), "uint160")
    return [_py_convert("address", "uint160", c) for c in cases]


def _cases_for_bool(_typ):
    return [True, False]


def _cases_for_bytes(typ):
    detail = _parse_type(typ)
    m_bits = detail.info.m_bits
    # reuse the cases for the equivalent int type
    equiv_int_type = f"uint{m_bits}"
    cases = _filter_cases(_cases_for_int(equiv_int_type), equiv_int_type)
    return [_py_convert(typ, equiv_int_type, c) for c in cases]


def _cases_for_Bytes(typ):
    ret = []
    # would not need this if we tested all Bytes[1]...Bytes[32] types.
    for i in range(32):
        ret.extend(_cases_for_bytes(f"bytes{i+1}"))
    return uniq(ret)


def cases_for_type(typ):
    detail = _parse_type(typ)
    if detail.type_class == "int":
        return _cases_for_int(typ)
    if detail.type_class == "decimal":
        return _cases_for_decimal(typ)
    if detail.type_class == "bytes":
        return _cases_for_bytes(typ)
    if detail.type_class == "Bytes":
        return _cases_for_Bytes(typ)
    if detail.type_class == "bool":
        return _cases_for_bool(typ)
    if detail.type_class == "address":
        return _cases_for_address(typ)


def _filter_cases(cases, i_typ):
    cases = uniq(cases)
    return [c for c in cases if _py_convert(c, i_typ, i_typ) is not None]


class _PadDirection(enum.auto):
    Left: str
    Right: str


def _padding_direction(typ):
    detail = _parse_type(typ)
    if detail.type_class in ("bytes", "String", "Bytes"):
        return _PadDirection.Right
    return _PadDirection.Left


def _padconvert(val_bits, direction, n):
    """
    Takes the ABI representation of a value, and convert the padding if needed.
    Note: do not strip dirty bytes, just swap the two halves of the bytestring.
    """
    assert len(val_bits) == 32

    # right- to left- padded
    if direction == _PadDirection.Left:
        return val_bits[-n:] + val_bits[:-n]

    # convert left-padded to right-padded
    if direction == _PadDirection.Right:
        return val_bits[n:] + val_bits[:n]


def _from_bits(val_bits, o_typ):
    # o_typ: the type to convert to
    detail = _parse_type(o_typ)
    try:
        return decode_single(detail.abi_type, val_bits)
    except eth_abi.exceptions.NonEmptyPaddingBytes:
        raise _OutOfBounds() from None


def _to_bits(val, i_typ):
    # i_typ: the type to convert from
    detail = _parse_type(i_typ)
    return encode_single(detail.abi_type, val)


def _signextend(val_bytes, bits):
    return _to_bits(f"int{bits}", unsigned_to_signed(int(val_bytes), bits))


def _convert_decimal_to_int(val, o_typ):
    if not SizeLimits.in_bounds(o_typ, val):
        raise _OutOfBounds(val)

    return round_towards_zero(val)


def _py_convert(o_typ, i_typ, val):
    """
    Perform conversion on the Python representation of a Vyper value.
    Returns None if the conversion is invalid (i.e., would revert in Vyper)
    """
    if i_typ.type_name == "decimal" and o_typ.type_name in INTEGER_TYPES:
        # note special behavior for decimal: catch OOB before truncation.
        try:
            val = _convert_decimal_to_int(val, o_typ)
        except _OutOfBounds:
            return None

    val_bits = _to_bits(val, i_typ)

    if i_typ.type_class in ("Bytes", "String"):
        val_bits = val_bits[-32:]

    if _padding_direction(i_typ) != _padding_direction(o_typ):
        n = o_typ.type_bytes
        val_bits = _padconvert(val_bits, _padding_direction(o_typ), n)

    if getattr(o_typ.info, "is_signed", False):
        val_bits = _signextend(val_bits)

    try:
        return _from_bits(val_bits, o_typ)

    except _OutOfBounds:
        return None


@pytest.fixture
def all_pairs():
    return itertools.product(BASE_TYPES, BASE_TYPES)


@pytest.fixture
def allowed_pairs(all_pairs):
    return [(i, o) for (i, o) in all_pairs if can_convert(i, o)]


@pytest.fixture
def disallowed_pairs(all_pairs):
    return [(i, o) for (i, o) in all_pairs if not can_convert(i, o)]


# TODO double check scoping
@pytest.fixture
def cases_for_pair(i_typ, o_typ):
    """
    Fixture to generate all cases for pair
    """
    cases = cases_for_type(i_typ) + cases_for_type(o_typ)

    # only return cases which are valid for the input type
    return _filter_cases(cases, i_typ)


@pytest.fixture
def passing_cases_for_pair(i_typ, o_typ, cases_for_pair):
    """
    Fixture to generate passing test cases for a pair of types.
    """
    return [c for c in cases_for_pair if _py_convert(c, i_typ, o_typ) is not None]


@pytest.fixture
def failing_cases_for_pair(i_typ, o_typ, cases_for_pair):
    """
    Fixture to generate test cases which should raise either a compile time
    failure or runtime revert
    """
    return [c for c in cases_for_pair if _py_convert(c, i_typ, o_typ) is None]


@pytest.mark.parametrize("i_typ,o_typ", allowed_pairs)
@pytest.mark.parametrize("val", passing_cases_for_pair)
@pytest.mark.fuzzing
def test_convert_pass(get_contract_with_gas_estimation, assert_compile_failed, i_typ, o_typ, val):
    contract_1 = f"""
@external
def test_convert() -> {o_typ}:
    return convert({val}, {o_typ})
    """

    c1_exception = None
    if i_typ.startswith(("int", "uint")) and o_typ.startswith(("int", "uint")):
        # Skip conversion of positive integer literals because compiler reads them
        # as target type.
        if val >= 0:
            c1_exception = InvalidLiteral

    # if i_typ.startswith(("bytes", "Bytes")) and o_typ.startswith(("int", "uint", "decimal")):
    # Raw bytes are treated as uint256
    # skip_c1 = True

    # if in_type.startswith(("int", "uint")) and out_type.startswith("bytes"):
    # Skip conversion of integer literals because they are of uint256 / int256
    # types, unless it is bytes32
    # if out_type != "bytes32":
    #    skip_c1 = True

    # if in_type.startswith("Bytes") and out_type.startswith("bytes"):
    # Skip if length of Bytes[N] is same as size of bytesM
    # if len(val) == parse_bytes_m_info(out_type).m:
    #    skip_c1 = True

    # if in_type.startswith("bytes") and parse_bytes_m_info(in_type).m != 32:
    # Skip bytesN other than bytes32 because they get read as bytes32
    #    skip_c1 = True

    if i_typ.startswith("address") and o_typ == "bytes20":
        # Skip because raw address value is treated as bytes20
        # skip_c1 = True
        pass

    if c1_exception is not None:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract_1), c1_exception)
    else:
        c1 = get_contract_with_gas_estimation(contract_1)
        assert c1.test_convert() == _py_convert(val)

    contract_2 = f"""
@external
def test_input_convert(x: {i_typ}) -> {o_typ}:
    return convert(x, {o_typ})
    """

    c2 = get_contract_with_gas_estimation(contract_2)
    assert c2.test_input_convert(val) == _py_convert(val)

    contract_3 = f"""
bar: {i_typ}

@external
def test_state_variable_convert() -> {o_typ}:
    self.bar = {i_typ}
    return convert(self.bar, {o_typ})
    """

    c3 = get_contract_with_gas_estimation(contract_3)
    assert c3.test_state_variable_convert() == _py_convert(val)

    contract_4 = f"""
@external
def test_memory_variable_convert() -> {o_typ}:
    bar: {i_typ} = {val}
    return convert(bar, {o_typ})
    """

    c4 = get_contract_with_gas_estimation(contract_4)
    assert c4.test_state_variable_convert() == _py_convert(val)


# TODO CMC 2022-04-06 I think this test is somewhat unnecessary.
@pytest.mark.parametrize(
    "builtin_constant,out_type,out_value",
    [
        ("ZERO_ADDRESS", "bool", False),
        ("msg.sender", "bool", True),
    ],
)
def test_convert_builtin_constant(
    get_contract_with_gas_estimation, builtin_constant, out_type, out_value
):

    contract = f"""
@external
def convert_builtin_constant() -> {out_type}:
    return convert({builtin_constant}, {out_type})
    """

    c = get_contract_with_gas_estimation(contract)
    assert c.convert_builtin_constant() == out_value


# uint256 conversion is currently valid due to type inference on literals
# not quite working yet
same_type_conversion_blocked = TEST_TYPES - {"uint256"}


@pytest.mark.parametrized("typ", same_type_conversion_blocked)
def test_same_type_conversion_blocked(get_contract, assert_compile_failed, typ):
    code = """
@external
def foo(x: {typ}) -> {typ}:
    return convert(x, {typ})
    """
    assert_compile_failed(lambda: get_contract(code), InvalidType)


@pytest.mark.parametrized("typ", disallowed_pairs)
def test_type_conversion_blocked(get_contract, assert_compile_failed, typ):
    code = """
@external
def foo(x: {typ}) -> {typ}:
    return convert(x, {typ})
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize(TEST_TYPES)
def test_bytes_too_large_cases(get_contract, assert_compile_failed, typ):
    code_1 = """
@external
def foo(x: Bytes[33]) -> {typ}:
    return convert(x, {typ})
    """
    assert_compile_failed(lambda: get_contract(code_1), TypeMismatch)

    bytes_33 = b"1" * 33
    code_2 = f"""
@external
def foo() -> {typ}:
    return convert({bytes_33}, {typ})
    """

    assert_compile_failed(lambda: get_contract(code_2, TypeMismatch))


@pytest.mark.parametrize("i_typ,o_typ", allowed_pairs)
@pytest.mark.parametrize("val", failing_cases_for_pair)
@pytest.mark.fuzzing
def test_conversion_failures(
    get_contract_with_gas_estimation, assert_compile_failed, assert_tx_failed, i_typ, o_typ, val
):
    """
    Test multiple contracts and check for a specific exception.
    If no exception is provided, a runtime revert is expected (e.g. clamping).
    """
    skip_c1 = False

    if i_typ.startswith("int") and o_typ == "address":
        skip_c1 = True

    if i_typ.startswith("bytes"):
        skip_c1 = True

    if i_typ == "address":
        skip_c1 = True

    contract_1 = f"""
@external
def foo() -> {o_typ}:
    return convert({val}, {o_typ})
    """

    if not skip_c1:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract_1),
            InvalidLiteral,
        )

    contract_2 = f"""
@external
def foo():
    bar: {i_typ} = {val}
    foobar: {o_typ} = convert(bar, {o_typ})
    """

    c2 = get_contract_with_gas_estimation(contract_2)
    assert_tx_failed(lambda: c2.foo())

    contract_3 = f"""
@external
def foo(bar: {i_typ}) -> {o_typ}:
    return convert(bar, {o_typ})
    """

    c3 = get_contract_with_gas_estimation(contract_3)
    assert_tx_failed(lambda: c3.foo(val))
