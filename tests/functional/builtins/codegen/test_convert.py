import enum
import itertools

# import random
from decimal import Decimal

import eth.codecs.abi as abi
import eth.codecs.abi.exceptions
import pytest

from vyper.compiler import compile_code
from vyper.exceptions import InvalidLiteral, InvalidType, TypeMismatch
from vyper.semantics.types import AddressT, BoolT, BytesM_T, BytesT, DecimalT, IntegerT, StringT
from vyper.semantics.types.shortcuts import BYTES20_T, BYTES32_T, UINT, UINT160_T, UINT256_T
from vyper.utils import (
    DECIMAL_DIVISOR,
    checksum_encode,
    int_bounds,
    is_checksum_encoded,
    round_towards_zero,
    unsigned_to_signed,
)

BASE_TYPES = set(IntegerT.all()) | set(BytesM_T.all()) | {DecimalT(), AddressT(), BoolT()}

TEST_TYPES = BASE_TYPES | {BytesT(32)} | {StringT(32)}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# decimal increment, aka smallest decimal > 0
DECIMAL_EPSILON = Decimal(1) / DECIMAL_DIVISOR


def _bits_of_type(typ):
    if isinstance(typ, (IntegerT, DecimalT)):
        return typ.bits
    if isinstance(typ, BoolT):
        return 8
    if isinstance(typ, AddressT):
        return 160
    if isinstance(typ, BytesM_T):
        return typ.m_bits
    if isinstance(typ, BytesT):
        return typ.length * 8

    raise Exception(f"Unknown type {typ}")


def bytes_of_type(typ):
    ret = _bits_of_type(typ)
    assert ret % 8 == 0
    return ret // 8


class _OutOfBounds(Exception):
    """
    A Python-level conversion is out of bounds
    """

    pass


def can_convert(i_typ, o_typ):
    """
    Checks whether conversion from one type to another is valid.
    """
    if i_typ == o_typ:
        return False

    if isinstance(o_typ, BoolT):
        return True
    if isinstance(i_typ, BoolT):
        return not isinstance(o_typ, AddressT)

    if isinstance(i_typ, IntegerT):
        if isinstance(o_typ, BytesM_T):
            return bytes_of_type(i_typ) <= bytes_of_type(o_typ)

        ret = isinstance(o_typ, (IntegerT, DecimalT, BytesM_T, BytesT))
        if not i_typ.is_signed:
            ret |= isinstance(o_typ, AddressT)
        return ret

    if isinstance(i_typ, BytesM_T):
        if isinstance(o_typ, BytesT):
            # bytesN must be of equal or smaller size to the input
            return bytes_of_type(i_typ) <= bytes_of_type(o_typ)

        return isinstance(o_typ, (DecimalT, BytesM_T, IntegerT, AddressT))

    if isinstance(i_typ, BytesT):
        return isinstance(o_typ, (IntegerT, DecimalT, AddressT))

    if isinstance(i_typ, DecimalT):
        if isinstance(o_typ, BytesM_T):
            return bytes_of_type(i_typ) <= bytes_of_type(o_typ)

        return isinstance(o_typ, (IntegerT, BoolT))

    if isinstance(i_typ, AddressT):
        if isinstance(o_typ, BytesM_T):
            return bytes_of_type(i_typ) <= bytes_of_type(o_typ)
        if isinstance(o_typ, IntegerT):
            return not o_typ.is_signed
        return False

    raise AssertionError(f"unreachable {i_typ} {o_typ}")


def uniq(xs):
    return list(set(xs))


def _cases_for_int(typ):
    lo, hi = typ.ast_bounds

    ret = [lo - 1, lo, lo + 1, -1, 0, 1, hi - 1, hi, hi + 1]

    # random cases cause reproducibility issues. TODO fixme
    # NUM_RANDOM_CASES = 6
    # ret.extend(random.randrange(lo, hi) for _ in range(NUM_RANDOM_CASES))

    return ret


def _cases_for_decimal(typ):
    lo, hi = typ.ast_bounds

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
    cases = _filter_cases(_cases_for_int(UINT160_T), UINT160_T)
    return [_py_convert(c, UINT160_T, AddressT()) for c in cases]


def _cases_for_bool(_typ):
    return [True, False]


def _cases_for_bytes(typ):
    # reuse the cases for the equivalent int type
    equiv_int_type = UINT(typ.m_bits)
    cases = _filter_cases(_cases_for_int(equiv_int_type), equiv_int_type)
    return [_py_convert(c, equiv_int_type, typ) for c in cases]


def _cases_for_Bytes(typ):
    ret = []
    # would not need this if we tested all Bytes[1]...Bytes[32] types.
    for i in range(32):
        ret.extend(_cases_for_bytes(BytesM_T(i + 1)))

    ret.append(b"")
    return uniq(ret)


def _cases_for_String(typ):
    ret = []
    # would not need this if we tested all Bytes[1]...Bytes[32] types.
    for i in range(32):
        ret.extend([str(c, "utf-8") for c in _cases_for_bytes(BytesM_T(i + 1))])
    ret.append("")
    return uniq(ret)


# generate all cases of interest for a type, potentially including invalid cases
def interesting_cases_for_type(typ):
    if isinstance(typ, IntegerT):
        return _cases_for_int(typ)
    if isinstance(typ, DecimalT):
        return _cases_for_decimal(typ)
    if isinstance(typ, BytesM_T):
        return _cases_for_bytes(typ)
    if isinstance(typ, BytesT):
        return _cases_for_Bytes(typ)
    if isinstance(typ, StringT):
        return _cases_for_String(typ)
    if isinstance(typ, BoolT):
        return _cases_for_bool(typ)
    if isinstance(typ, AddressT):
        return _cases_for_address(typ)


def _filter_cases(cases, i_typ):
    cases = uniq(cases)

    def _in_bounds(c):
        try:
            return _py_convert(c, i_typ, i_typ) is not None
        except eth.codecs.abi.exceptions.EncodeError:
            return False

    return [c for c in cases if _in_bounds(c)]


class _PadDirection(enum.Enum):
    Left = enum.auto()
    Right = enum.auto()


def _padding_direction(typ):
    if isinstance(typ, (BytesM_T, StringT, BytesT)):
        return _PadDirection.Right
    return _PadDirection.Left


# TODO this could be a function in vyper.builtins._convert
# which implements literal folding and also serves as a reference/spec
def _padconvert(val_bits, direction, n, padding_byte=None):
    """
    Takes the ABI representation of a value, and convert the padding if needed.
    If fill_zeroes is false, the two halves of the bytestring are just swapped
    and the dirty bytes remain dirty. If fill_zeroes is true, the padding
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
    try:
        return abi.decode(o_typ.abi_type.selector_name(), val_bits)
    except eth.codecs.abi.exceptions.DecodeError:
        raise _OutOfBounds() from None


def _to_bits(val, i_typ):
    # i_typ: the type to convert from
    return abi.encode(i_typ.abi_type.selector_name(), val)


def _signextend(val_bytes, bits):
    as_uint = int.from_bytes(val_bytes, byteorder="big")

    as_sint = unsigned_to_signed(as_uint, bits)

    return (as_sint % 2**256).to_bytes(32, byteorder="big")


def _convert_int_to_int(val, o_typ):
    lo, hi = o_typ.int_bounds
    if not lo <= val <= hi:
        return None
    return val


def _convert_decimal_to_int(val, o_typ):
    # note special behavior for decimal: catch OOB before truncation.
    lo, hi = o_typ.int_bounds
    if not lo <= val <= hi:
        return None

    return round_towards_zero(val)


def _convert_int_to_decimal(val, o_typ):
    ret = Decimal(val)
    lo, hi = o_typ.ast_bounds

    if not lo <= ret <= hi:
        return None

    return ret


def _py_convert(val, i_typ, o_typ):
    """
    Perform conversion on the Python representation of a Vyper value.
    Returns None if the conversion is invalid (i.e., would revert in Vyper)
    """

    if isinstance(i_typ, IntegerT) and isinstance(o_typ, IntegerT):
        return _convert_int_to_int(val, o_typ)

    if isinstance(i_typ, DecimalT) and isinstance(o_typ, IntegerT):
        return _convert_decimal_to_int(val, o_typ)

    if isinstance(i_typ, (BoolT, IntegerT)) and isinstance(o_typ, DecimalT):
        # Note: Decimal(True) == Decimal("1")
        return _convert_int_to_decimal(val, o_typ)

    val_bits = _to_bits(val, i_typ)

    if isinstance(i_typ, (BytesT, StringT)):
        val_bits = val_bits[32:]

    if _padding_direction(i_typ) != _padding_direction(o_typ):
        # subtle! the padding conversion follows the bytes argument
        if isinstance(i_typ, (BytesM_T, BytesT)):
            n = bytes_of_type(i_typ)
            padding_byte = None
        else:
            # output type is bytes
            n = bytes_of_type(o_typ)
            padding_byte = b"\x00"

        val_bits = _padconvert(val_bits, _padding_direction(o_typ), n, padding_byte)

    if getattr(o_typ, "is_signed", False) and isinstance(i_typ, BytesM_T):
        n_bits = _bits_of_type(i_typ)
        val_bits = _signextend(val_bits, n_bits)

    try:
        if isinstance(o_typ, BoolT):
            return _from_bits(val_bits, UINT256_T) != 0

        ret = _from_bits(val_bits, o_typ)

        if isinstance(o_typ, AddressT):
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
        except eth.codecs.abi.exceptions.EncodeError:
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
    if isinstance(typ, BytesM_T):
        return "0x" + val.hex()
    if isinstance(typ, DecimalT):
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
    if isinstance(o_typ, AddressT) and expected_val == "0x" + "00" * 20:
        # web3 has special formatter for zero address
        expected_val = None

    contract_1 = f"""
@external
def test_convert() -> {o_typ}:
    return convert({_vyper_literal(val, i_typ)}, {o_typ})
    """

    c1_exception = None
    skip_c1 = False

    # Skip bytes20 literals when there is ambiguity with `address` since address takes precedence.
    # generally happens when there are only digits in the literal.
    if i_typ == BYTES20_T and is_checksum_encoded(_vyper_literal(val, BYTES20_T)):
        skip_c1 = True

    # typechecker inference borked, ambiguity with bytes20
    if isinstance(i_typ, AddressT) and o_typ == BYTES20_T and val == val.lower():
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


@pytest.mark.parametrize("typ", ["uint8", "int128", "int256", "uint256"])
@pytest.mark.parametrize("val", [1, 2, 2**128, 2**256 - 1, 2**256 - 2])
def test_flag_conversion(get_contract_with_gas_estimation, assert_compile_failed, val, typ):
    roles = "\n    ".join([f"ROLE_{i}" for i in range(256)])
    contract = f"""
flag Roles:
    {roles}

@external
def foo(a: Roles) -> {typ}:
    return convert(a, {typ})

@external
def bar(a: uint256) -> Roles:
    return convert(a, Roles)
    """
    if typ == "uint256":
        c = get_contract_with_gas_estimation(contract)
        assert c.foo(val) == val
        assert c.bar(val) == val
    else:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), TypeMismatch)


@pytest.mark.parametrize("typ", ["uint8", "int128", "int256", "uint256"])
@pytest.mark.parametrize("val", [1, 2, 3, 4, 2**128, 2**256 - 1, 2**256 - 2])
def test_flag_conversion_2(
    get_contract_with_gas_estimation, assert_compile_failed, tx_failed, val, typ
):
    contract = f"""
flag Status:
    STARTED
    PAUSED
    STOPPED

@external
def foo(a: {typ}) -> Status:
    return convert(a, Status)
    """
    if typ == "uint256":
        c = get_contract_with_gas_estimation(contract)
        lo, hi = int_bounds(signed=False, bits=3)
        if lo <= val <= hi:
            assert c.foo(val) == val
        else:
            with tx_failed():
                c.foo(val)
    else:
        assert_compile_failed(lambda: get_contract_with_gas_estimation(contract), TypeMismatch)


# uint256 conversion is currently valid due to type inference on literals
# not quite working yet
same_type_conversion_blocked = sorted(TEST_TYPES - {UINT256_T})


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


@pytest.mark.parametrize("typ", sorted(BASE_TYPES))
def test_bytes_too_large_cases(typ):
    code_1 = f"""
@external
def foo(x: Bytes[33]) -> {typ}:
    return convert(x, {typ})
    """
    with pytest.raises(TypeMismatch):
        compile_code(code_1)

    bytes_33 = b"1" * 33
    code_2 = f"""
@external
def foo() -> {typ}:
    return convert({bytes_33}, {typ})
    """
    with pytest.raises(TypeMismatch):
        compile_code(code_2)


@pytest.mark.parametrize("cls1,cls2", itertools.product((StringT, BytesT), (StringT, BytesT)))
def test_bytestring_conversions(cls1, cls2, get_contract, tx_failed):
    typ1 = cls1(33)
    typ2 = cls2(32)

    def bytestring(cls, string):
        if cls == BytesT:
            return string.encode("utf-8")
        return string

    code_1 = f"""
@external
def foo(x: {typ1}) -> {typ2}:
    return convert(x, {typ2})
    """
    c = get_contract(code_1)

    for i in range(33):  # inclusive 32
        s = "1" * i
        arg = bytestring(cls1, s)
        out = bytestring(cls2, s)
        assert c.foo(arg) == out

    with tx_failed():
        # TODO: sanity check it is convert which is reverting, not arg clamping
        c.foo(bytestring(cls1, "1" * 33))

    code_2_template = """
@external
def foo() -> {typ}:
    return convert({arg}, {typ})
    """

    # test literals
    for i in range(33):  # inclusive 32
        s = "1" * i
        arg = bytestring(cls1, s)
        out = bytestring(cls2, s)
        code = code_2_template.format(typ=typ2, arg=repr(arg))
        if cls1 == cls2:  # ex.: can't convert "" to String[32]
            with pytest.raises(InvalidType):
                compile_code(code)
        else:
            c = get_contract(code)
            assert c.foo() == out

    failing_code = code_2_template.format(typ=typ2, arg=bytestring(cls1, "1" * 33))
    with pytest.raises(TypeMismatch):
        compile_code(failing_code)


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
    get_contract_with_gas_estimation, assert_compile_failed, tx_failed, i_typ, o_typ, val
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

    if isinstance(i_typ, IntegerT) and isinstance(o_typ, BytesM_T):
        # integer literals get upcasted to uint256 / int256 types, so the convert
        # will not compile unless it is bytes32
        if o_typ != BYTES32_T:
            c1_exception = TypeMismatch

    # compile-time folding not implemented for these:
    skip_c1 = False
    # if isinstance(o_typ, IntegerT.signeds()) and isinstance(i_typ, Address()):
    #    skip_c1 = True

    if isinstance(o_typ, BytesM_T):
        skip_c1 = True

    # if o_typ in (AddressT(), BYTES20_T):
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
    with tx_failed():
        c2.foo()

    contract_3 = f"""
@external
def foo(bar: {i_typ}) -> {o_typ}:
    return convert(bar, {o_typ})
    """

    c3 = get_contract_with_gas_estimation(contract_3)
    with tx_failed():
        c3.foo(val)
