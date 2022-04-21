import enum
import itertools

# import random
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import eth_abi.exceptions
import pytest
from eth_abi import decode_single, encode_single

from vyper.codegen.types import (
    BASE_TYPES,
    INTEGER_TYPES,
    SIGNED_INTEGER_TYPES,
    parse_bytes_m_info,
    parse_decimal_info,
    parse_integer_typeinfo,
)
from vyper.exceptions import InvalidLiteral, InvalidType, TypeMismatch
from vyper.utils import (
    DECIMAL_DIVISOR,
    SizeLimits,
    checksum_encode,
    is_checksum_encoded,
    round_towards_zero,
    unsigned_to_signed,
)

TEST_TYPES = BASE_TYPES | {"Bytes[32]"}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# decimal increment, aka smallest decimal > 0
DECIMAL_EPSILON = Decimal(1) / DECIMAL_DIVISOR


@dataclass
class TestType:
    """
    Simple class to model Vyper types.
    """

    type_name: str
    type_bytes: int  # number of nonzero bytes this type can take
    type_class: str  # e.g. int, bytes, String, decimal
    info: Any  # e.g. DecimalInfo

    @property
    def abi_type(self):
        if self.type_name == "decimal":
            return "fixed168x10"
        if self.type_class in ("Bytes", "String"):
            return self.type_class.lower()
        return self.type_name


class _OutOfBounds(Exception):
    """
    A Python-level conversion is out of bounds
    """

    pass


def _parse_type(typename):
    if typename.startswith(("uint", "int")):
        info = parse_integer_typeinfo(typename)
        assert info.bits % 8 == 0
        return TestType(typename, info.bits // 8, "int", info)
    elif typename == "decimal":
        info = parse_decimal_info(typename)
        assert info.bits % 8 == 0
        return TestType(typename, info.bits // 8, "decimal", info)
    elif typename.startswith("bytes"):
        info = parse_bytes_m_info(typename)
        return TestType(typename, info.m, "bytes", info)
    elif typename.startswith("Bytes"):
        assert typename == "Bytes[32]"  # TODO test others
        return TestType(typename, 32, "Bytes", None)
    elif typename.startswith("String"):
        assert typename == "String[32]"  # TODO test others
        return TestType(typename, 32, "String", None)
    elif typename == "address":
        return TestType(typename, 20, "address", None)
    elif typename == "bool":
        return TestType(typename, 1, "bool", None)

    raise AssertionError(f"no info {typename}")


def can_convert(i_typ, o_typ):
    """
    Checks whether conversion from one type to another is valid.
    """
    if i_typ == o_typ:
        return False

    i_detail = _parse_type(i_typ)
    o_detail = _parse_type(o_typ)

    if o_typ == "bool":
        return True
    if i_typ == "bool":
        return o_typ not in {"address"}

    if i_detail.type_class == "int":
        if o_detail.type_class == "bytes":
            return i_detail.type_bytes <= o_detail.type_bytes

        ret = o_detail.type_class in ("int", "decimal", "bytes", "Bytes")
        if not i_detail.info.is_signed:
            ret |= o_typ == "address"
        return ret

    elif i_detail.type_class == "bytes":
        if o_detail.type_class == "Bytes":
            # bytesN must be of equal or smaller size to the input
            return i_detail.type_bytes <= o_detail.type_bytes

        return o_detail.type_class in ("decimal", "bytes", "int", "address")

    elif i_detail.type_class == "Bytes":
        return o_detail.type_class in ("int", "decimal", "address")

    elif i_typ == "decimal":
        if o_detail.type_class == "bytes":
            return i_detail.type_bytes <= o_detail.type_bytes

        return o_detail.type_class in ("int", "bool")

    elif i_typ == "address":
        if o_detail.type_class == "bytes":
            return i_detail.type_bytes <= o_detail.type_bytes
        elif o_detail.type_class == "int":
            return not o_detail.info.is_signed
        return False

    raise AssertionError(f"unreachable {i_typ} {o_typ}")


def uniq(xs):
    return list(set(xs))


def _cases_for_int(typ):
    info = parse_integer_typeinfo(typ)

    lo, hi = info.bounds

    ret = [lo - 1, lo, lo + 1, -1, 0, 1, hi - 1, hi, hi + 1]

    # random cases cause reproducibility issues. TODO fixme
    # NUM_RANDOM_CASES = 6
    # ret.extend(random.randrange(lo, hi) for _ in range(NUM_RANDOM_CASES))

    return ret


def _cases_for_decimal(typ):
    info = parse_decimal_info(typ)

    lo, hi = info.decimal_bounds

    ret = [Decimal(i) for i in [-1, 0, 1]]
    ret.extend([lo - 1, lo, lo + 1, hi - 1, hi, hi + 1])

    ret.extend(
        [lo - DECIMAL_EPSILON, lo + DECIMAL_EPSILON, hi - DECIMAL_EPSILON, hi + DECIMAL_EPSILON]
    )

    # random cases cause reproducibility issues. TODO fixme
    # (use int values because randrange can't generate fractional decimals)
    # int_lo, int_hi = info.bounds  # e.g. -(2**167)
    # NUM_RANDOM_CASES = 10  # more than int, just for paranoia's sake
    # DIVISOR = info.divisor
    # ret.extend(random.randrange(int_lo, int_hi) / DIVISOR for _ in range(NUM_RANDOM_CASES))

    return ret


def _cases_for_address(_typ):
    cases = _filter_cases(_cases_for_int("uint160"), "uint160")
    return [_py_convert(c, "uint160", "address") for c in cases]


def _cases_for_bool(_typ):
    return [True, False]


def _cases_for_bytes(typ):
    detail = _parse_type(typ)
    m_bits = detail.info.m_bits
    # reuse the cases for the equivalent int type
    equiv_int_type = f"uint{m_bits}"
    cases = _filter_cases(_cases_for_int(equiv_int_type), equiv_int_type)
    return [_py_convert(c, equiv_int_type, typ) for c in cases]


def _cases_for_Bytes(typ):
    ret = []
    # would not need this if we tested all Bytes[1]...Bytes[32] types.
    for i in range(32):
        ret.extend(_cases_for_bytes(f"bytes{i+1}"))
    return uniq(ret)


# generate all cases of interest for a type, potentially including invalid cases
def interesting_cases_for_type(typ):
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

    def _in_bounds(c):
        try:
            return _py_convert(c, i_typ, i_typ) is not None
        except eth_abi.exceptions.ValueOutOfBounds:
            return False

    return [c for c in cases if _in_bounds(c)]


class _PadDirection(enum.Enum):
    Left = enum.auto()
    Right = enum.auto()


def _padding_direction(typ):
    detail = _parse_type(typ)
    if detail.type_class in ("bytes", "String", "Bytes"):
        return _PadDirection.Right
    return _PadDirection.Left


# TODO this could be a function in vyper.builtin_functions.convert
# which implements literal folding and also serves as a reference/spec
def _padconvert(val_bits, direction, n, padding_byte=None):
    """
    Takes the ABI representation of a value, and convert the padding if needed.
    If fill_zeroes is false, the two halves of the bytestring are just swapped
    and the dirty bytes remain dirty. If fill_zeroes is true, the the padding
    bytes get set to 0
    """
    assert len(val_bits) == 32

    # convert left-padded to right-padded
    if direction == _PadDirection.Right:
        tail = val_bits[:-n]
        if padding_byte is not None:
            tail = padding_byte * len(tail)
        return val_bits[-n:] + tail

    # right- to left- padded
    if direction == _PadDirection.Left:
        head = val_bits[n:]
        if padding_byte is not None:
            head = padding_byte * len(head)
        return head + val_bits[:n]


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
    as_uint = int.from_bytes(val_bytes, byteorder="big")

    as_sint = unsigned_to_signed(as_uint, bits)

    return (as_sint % 2 ** 256).to_bytes(32, byteorder="big")


def _convert_decimal_to_int(val, o_typ):
    # note special behavior for decimal: catch OOB before truncation.
    if not SizeLimits.in_bounds(o_typ, val):
        return None

    return round_towards_zero(val)


def _convert_int_to_decimal(val, o_typ):
    detail = _parse_type(o_typ)
    ret = Decimal(val)
    # note: SizeLimits.in_bounds is for the EVM int value, not the python value
    lo, hi = detail.info.decimal_bounds
    if not lo <= ret <= hi:
        return None

    return ret


def _py_convert(val, i_typ, o_typ):
    """
    Perform conversion on the Python representation of a Vyper value.
    Returns None if the conversion is invalid (i.e., would revert in Vyper)
    """
    i_detail = _parse_type(i_typ)
    o_detail = _parse_type(o_typ)

    if i_detail.type_class == "int" and o_detail.type_class == "int":
        if not SizeLimits.in_bounds(o_typ, val):
            return None
        return val

    if i_typ == "decimal" and o_typ in INTEGER_TYPES:
        return _convert_decimal_to_int(val, o_typ)

    if i_detail.type_class in ("bool", "int") and o_typ == "decimal":
        # Note: Decimal(True) == Decimal("1")
        return _convert_int_to_decimal(val, o_typ)

    val_bits = _to_bits(val, i_typ)

    if i_detail.type_class in ("Bytes", "String"):
        val_bits = val_bits[32:]

    if _padding_direction(i_typ) != _padding_direction(o_typ):
        # subtle! the padding conversion follows the bytes argument
        if i_detail.type_class in ("bytes", "Bytes"):
            n = i_detail.type_bytes
            padding_byte = None
        else:
            # output type is bytes
            n = o_detail.type_bytes
            padding_byte = b"\x00"

        val_bits = _padconvert(val_bits, _padding_direction(o_typ), n, padding_byte)

    if getattr(o_detail.info, "is_signed", False) and i_detail.type_class == "bytes":
        n_bits = i_detail.type_bytes * 8
        val_bits = _signextend(val_bits, n_bits)

    try:
        if o_typ == "bool":
            return _from_bits(val_bits, "uint256") != 0

        ret = _from_bits(val_bits, o_typ)

        if o_typ == "address":
            return checksum_encode(ret)
        return ret

    except _OutOfBounds:
        return None


# the matrix of all type pairs
def all_pairs():
    return sorted(itertools.product(BASE_TYPES, BASE_TYPES))


# pairs which can compile
def convertible_pairs():
    return [(i, o) for (i, o) in all_pairs() if can_convert(i, o)]


# pairs which shouldn't even compile
def non_convertible_pairs():
    return [(i, o) for (i, o) in all_pairs() if not can_convert(i, o) and i != o]


# _CASES_CACHE = {}


def cases_for_pair(i_typ, o_typ):
    """
    Helper function to generate all cases for pair
    """
    # if (i_typ, o_typ) in _CASES_CACHE:
    #    # cache the cases for reproducibility, to ensure test_passing_cases and test_failing_cases
    #    # test exactly the two halves of the produced cases.
    #    return _CASES_CACHE[(i_typ, o_typ)]

    cases = interesting_cases_for_type(i_typ)
    # only return cases which are valid for the input type
    cases = _filter_cases(cases, i_typ)

    for c in interesting_cases_for_type(o_typ):
        # convert back into i_typ
        try:
            c = _py_convert(c, o_typ, i_typ)
            if c is not None:
                cases.append(c)
        except eth_abi.exceptions.ValueOutOfBounds:
            pass

    # _CASES_CACHE[(i_typ, o_typ)] = cases

    return cases


def generate_passing_cases():
    ret = []
    for i_typ, o_typ in convertible_pairs():
        cases = cases_for_pair(i_typ, o_typ)
        for c in cases:
            # only add convertible cases
            if _py_convert(c, i_typ, o_typ) is not None:
                ret.append((i_typ, o_typ, c))
    return sorted(ret)


def generate_reverting_cases():
    ret = []
    for i_typ, o_typ in convertible_pairs():
        cases = cases_for_pair(i_typ, o_typ)
        for c in cases:
            if _py_convert(c, i_typ, o_typ) is None:
                ret.append((i_typ, o_typ, c))
    return sorted(ret)


def _vyper_literal(val, typ):
    detail = _parse_type(typ)
    if detail.type_class == "bytes":
        return "0x" + val.hex()
    if detail.type_class == "decimal":
        tmp = val
        val = val.quantize(DECIMAL_EPSILON)
        assert tmp == val
    return str(val)


@pytest.mark.parametrize("i_typ,o_typ,val", generate_passing_cases())
@pytest.mark.fuzzing
def test_convert_passing(
    get_contract_with_gas_estimation, assert_compile_failed, i_typ, o_typ, val
):

    expected_val = _py_convert(val, i_typ, o_typ)
    if o_typ == "address" and expected_val == "0x" + "00" * 20:
        # web3 has special formatter for zero address
        expected_val = None

    contract_1 = f"""
@external
def test_convert() -> {o_typ}:
    return convert({_vyper_literal(val, i_typ)}, {o_typ})
    """

    c1_exception = None
    skip_c1 = False
    if i_typ in INTEGER_TYPES and o_typ in INTEGER_TYPES - {"uint256"}:
        # Skip conversion of positive integer literals because compiler reads them
        # as target type.
        if val >= 0:
            c1_exception = InvalidType

    if i_typ in SIGNED_INTEGER_TYPES and o_typ in SIGNED_INTEGER_TYPES and val < 0:
        # similar, skip conversion of negative integer literals because compiler
        # infers them as target type.
        c1_exception = InvalidType

    if i_typ.startswith(("int", "uint")) and o_typ.startswith("bytes"):
        # integer literals get upcasted to uint256 / int256 types, so the convert
        # will not compile unless it is bytes32
        if o_typ != "bytes32":
            c1_exception = TypeMismatch

    # Skip bytes20 literals when there is ambiguity with `address` since address takes precedence.
    # generally happens when there are only digits in the literal.
    if i_typ == "bytes20" and is_checksum_encoded(_vyper_literal(val, "bytes20")):
        skip_c1 = True

    # typechecker inference borked, ambiguity with bytes20
    if i_typ == "address" and o_typ == "bytes20" and val == val.lower():
        skip_c1 = True

    if c1_exception is not None:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract_1), c1_exception)
    elif not skip_c1:
        c1 = get_contract_with_gas_estimation(contract_1)
        assert c1.test_convert() == expected_val

    contract_2 = f"""
@external
def test_input_convert(x: {i_typ}) -> {o_typ}:
    return convert(x, {o_typ})
    """

    c2 = get_contract_with_gas_estimation(contract_2)
    assert c2.test_input_convert(val) == expected_val

    contract_3 = f"""
bar: {i_typ}

@external
def test_state_variable_convert() -> {o_typ}:
    self.bar = {_vyper_literal(val, i_typ)}
    return convert(self.bar, {o_typ})
    """

    c3 = get_contract_with_gas_estimation(contract_3)
    assert c3.test_state_variable_convert() == expected_val

    contract_4 = f"""
@external
def test_memory_variable_convert(x: {i_typ}) -> {o_typ}:
    y: {i_typ} = x
    return convert(y, {o_typ})
    """

    c4 = get_contract_with_gas_estimation(contract_4)
    assert c4.test_memory_variable_convert(val) == expected_val


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
same_type_conversion_blocked = sorted(TEST_TYPES - {"uint256"})


@pytest.mark.parametrize("typ", same_type_conversion_blocked)
def test_same_type_conversion_blocked(get_contract, assert_compile_failed, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return convert(x, {typ})
    """
    assert_compile_failed(lambda: get_contract(code), InvalidType)


@pytest.mark.parametrize("i_typ,o_typ", non_convertible_pairs())
def test_type_conversion_blocked(get_contract, assert_compile_failed, i_typ, o_typ):
    code = f"""
@external
def foo(x: {i_typ}) -> {o_typ}:
    return convert(x, {o_typ})
    """
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


@pytest.mark.parametrize("typ", sorted(TEST_TYPES))
def test_bytes_too_large_cases(get_contract, assert_compile_failed, typ):
    code_1 = f"""
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


@pytest.mark.parametrize("n", range(1, 33))
def test_Bytes_to_bytes(get_contract, n):
    t_bytes = f"bytes{n}"
    t_Bytes = f"Bytes[{n}]"

    test_data = b"\xff" * n

    code1 = f"""
@external
def foo() -> {t_bytes}:
    x: {t_Bytes} = {test_data}
    return convert(x, {t_bytes})
    """
    c1 = get_contract(code1)
    assert c1.foo() == test_data

    code2 = f"""
bar: {t_Bytes}
@external
def foo() -> {t_bytes}:
    self.bar = {test_data}
    return convert(self.bar, {t_bytes})
    """
    c2 = get_contract(code2)
    assert c2.foo() == test_data


@pytest.mark.parametrize("i_typ,o_typ,val", generate_reverting_cases())
@pytest.mark.fuzzing
def test_conversion_failures(
    get_contract_with_gas_estimation, assert_compile_failed, assert_tx_failed, i_typ, o_typ, val
):
    """
    Test multiple contracts and check for a specific exception.
    If no exception is provided, a runtime revert is expected (e.g. clamping).
    """
    contract_1 = f"""
@external
def foo() -> {o_typ}:
    return convert({_vyper_literal(val, i_typ)}, {o_typ})
    """

    c1_exception = InvalidLiteral

    if i_typ.startswith(("int", "uint")) and o_typ.startswith("bytes"):
        # integer literals get upcasted to uint256 / int256 types, so the convert
        # will not compile unless it is bytes32
        if o_typ != "bytes32":
            c1_exception = TypeMismatch

    # compile-time folding not implemented for these:
    skip_c1 = False
    # if o_typ.startswith("int") and i_typ == "address":
    #    skip_c1 = True

    if o_typ.startswith("bytes"):
        skip_c1 = True

    # if o_typ in ("address", "bytes20"):
    #    skip_c1 = True

    if not skip_c1:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract_1), c1_exception)

    contract_2 = f"""
@external
def foo():
    bar: {i_typ} = {_vyper_literal(val, i_typ)}
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
