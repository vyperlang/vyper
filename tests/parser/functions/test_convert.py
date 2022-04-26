import itertools

# import random
from decimal import Decimal

import eth_abi.exceptions
import pytest

from vyper.builtin_functions import can_convert, parse_type, py_convert
from vyper.codegen.types import BASE_TYPES, parse_decimal_info, parse_integer_typeinfo
from vyper.exceptions import InvalidLiteral, InvalidType, TypeMismatch
from vyper.utils import DECIMAL_DIVISOR, is_checksum_encoded

TEST_TYPES = BASE_TYPES | {"Bytes[32]"}

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# decimal increment, aka smallest decimal > 0
DECIMAL_EPSILON = Decimal(1) / DECIMAL_DIVISOR


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
    return [py_convert(c, "uint160", "address") for c in cases]


def _cases_for_bool(_typ):
    return [True, False]


def _cases_for_bytes(typ):
    detail = parse_type(typ)
    m_bits = detail.info.m_bits
    # reuse the cases for the equivalent int type
    equiv_int_type = f"uint{m_bits}"
    cases = _filter_cases(_cases_for_int(equiv_int_type), equiv_int_type)
    return [py_convert(c, equiv_int_type, typ) for c in cases]


def _cases_for_Bytes(typ):
    ret = []
    # would not need this if we tested all Bytes[1]...Bytes[32] types.
    for i in range(32):
        ret.extend(_cases_for_bytes(f"bytes{i+1}"))
    return uniq(ret)


# generate all cases of interest for a type, potentially including invalid cases
def interesting_cases_for_type(typ):
    detail = parse_type(typ)
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
            return py_convert(c, i_typ, i_typ) is not None
        except eth_abi.exceptions.ValueOutOfBounds:
            return False

    return [c for c in cases if _in_bounds(c)]


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
            c = py_convert(c, o_typ, i_typ)
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
            if py_convert(c, i_typ, o_typ) is not None:
                ret.append((i_typ, o_typ, c))
    return sorted(ret)


def generate_reverting_cases():
    ret = []
    for i_typ, o_typ in convertible_pairs():
        cases = cases_for_pair(i_typ, o_typ)
        for c in cases:
            if py_convert(c, i_typ, o_typ) is None:
                ret.append((i_typ, o_typ, c))
    return sorted(ret)


def _vyper_literal(val, typ):
    detail = parse_type(typ)
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

    expected_val = py_convert(val, i_typ, o_typ)
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


same_type_conversion_blocked = sorted(TEST_TYPES)


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
        # integer literals get casted to the smallest possible type, and raises
        # a TypeMismatch exception if out of bounds, except for bytes32 which requires
        # a value beyond all numeric types' bounds before it is out of bounds.
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
