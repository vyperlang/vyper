import itertools
import operator
import random

import pytest

from vyper.codegen.types.types import UNSIGNED_INTEGER_TYPES, parse_integer_typeinfo
from vyper.exceptions import InvalidType, OverflowException, ZeroDivisionException
from vyper.utils import SizeLimits, evm_div, evm_mod, int_bounds

PARAMS = []
for t in sorted(UNSIGNED_INTEGER_TYPES):
    info = parse_integer_typeinfo(t)
    lo, hi = int_bounds(bits=info.bits, signed=info.is_signed)
    PARAMS.append((t, lo, hi, info.bits))


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_exponent_base_zero(get_contract, typ, lo, hi, bits):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 0 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(42) == 0
    assert c.foo(hi) == 0


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_exponent_base_one(get_contract, typ, lo, hi, bits):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 1 ** x
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(hi) == 1


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_exponent_power_zero(get_contract, typ, lo, hi, bits):
    # #2984
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return x ** 0
    """
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(hi) == 1


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_exponent_power_one(get_contract, typ, lo, hi, bits):
    # #2984
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return x ** 1
    """
    c = get_contract(code)
    assert c.foo(0) == 0
    assert c.foo(1) == 1
    assert c.foo(42) == 42
    assert c.foo(hi) == hi


ARITHMETIC_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "/": evm_div,
    "%": evm_mod,
}


@pytest.mark.parametrize("op", sorted(ARITHMETIC_OPS.keys()))
@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
@pytest.mark.fuzzing
def test_arithmetic_thorough(
    get_contract, assert_tx_failed, assert_compile_failed, op, typ, lo, hi, bits
):
    # both variables
    code_1 = f"""
@external
def foo(x: {typ}, y: {typ}) -> {typ}:
    return x {op} y
    """
    # right is literal
    code_2_template = """
@external
def foo(x: {typ}) -> {typ}:
    return x {op} {y}
    """
    # left is literal
    code_3_template = """
@external
def foo(y: {typ}) -> {typ}:
    return {x} {op} y
    """
    # both literals
    code_4_template = """
@external
def foo() -> {typ}:
    return {x} {op} {y}
    """

    c = get_contract(code_1)

    fn = ARITHMETIC_OPS[op]

    special_cases = [0, 1, 2, 3, hi // 2 - 1, hi // 2, hi // 2 + 1, hi - 2, hi - 1, hi]
    xs = special_cases.copy()
    ys = special_cases.copy()
    NUM_CASES = 5
    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    xs += [random.randrange(lo, hi) for _ in range(NUM_CASES)]
    ys += [random.randrange(lo, hi) for _ in range(NUM_CASES)]

    # mirror signed integer tests
    assert 2 ** (bits - 1) in xs and (2 ** bits) - 1 in ys

    for (x, y) in itertools.product(xs, ys):
        expected = fn(x, y)
        in_bounds = SizeLimits.in_bounds(typ, expected)
        # safediv and safemod disallow divisor == 0
        div_by_zero = y == 0 and op in ("/", "%")

        ok = in_bounds and not div_by_zero

        code_2 = code_2_template.format(typ=typ, op=op, y=y)
        code_3 = code_3_template.format(typ=typ, op=op, x=x)
        code_4 = code_4_template.format(typ=typ, op=op, x=x, y=y)

        if ok:
            assert c.foo(x, y) == expected
            assert get_contract(code_2).foo(x) == expected
            assert get_contract(code_3).foo(y) == expected
            assert get_contract(code_4).foo() == expected
        elif div_by_zero:
            assert_tx_failed(lambda: c.foo(x, y))
            assert_compile_failed(lambda: get_contract(code_2), ZeroDivisionException)
            assert_tx_failed(lambda: get_contract(code_3).foo(y))
            assert_compile_failed(lambda: get_contract(code_4), ZeroDivisionException)
        else:
            assert_tx_failed(lambda: c.foo(x, y))
            assert_tx_failed(lambda: get_contract(code_2).foo(x))
            assert_tx_failed(lambda: get_contract(code_3).foo(y))
            assert_compile_failed(lambda: get_contract(code_4), (InvalidType, OverflowException))


COMPARISON_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@pytest.mark.parametrize("op", sorted(COMPARISON_OPS.keys()))
@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
@pytest.mark.fuzzing
def test_comparators(get_contract, op, typ, lo, hi, bits):
    code_1 = f"""
@external
def foo(x: {typ}, y: {typ}) -> bool:
    return x {op} y
    """

    fn = COMPARISON_OPS[op]

    c = get_contract(code_1)

    # note: constant folding is tested in tests/ast/folding

    special_cases = [0, 1, 2, 3, hi // 2 - 1, hi // 2, hi // 2 + 1, hi - 2, hi - 1, hi]
    xs = special_cases.copy()
    ys = special_cases.copy()

    for x, y in itertools.product(xs, ys):
        expected = fn(x, y)
        assert c.foo(x, y) is expected


# TODO move to tests/parser/functions/test_mulmod.py and test_addmod.py
def test_uint256_mod(assert_tx_failed, get_contract_with_gas_estimation):
    uint256_code = """
@external
def _uint256_addmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_addmod(x, y, z)

@external
def _uint256_mulmod(x: uint256, y: uint256, z: uint256) -> uint256:
    return uint256_mulmod(x, y, z)
    """

    c = get_contract_with_gas_estimation(uint256_code)

    assert c._uint256_addmod(1, 2, 2) == 1
    assert c._uint256_addmod(32, 2, 32) == 2
    assert c._uint256_addmod((2 ** 256) - 1, 0, 2) == 1
    assert c._uint256_addmod(2 ** 255, 2 ** 255, 6) == 4
    assert_tx_failed(lambda: c._uint256_addmod(1, 2, 0))
    assert c._uint256_mulmod(3, 1, 2) == 1
    assert c._uint256_mulmod(200, 3, 601) == 600
    assert c._uint256_mulmod(2 ** 255, 1, 3) == 2
    assert c._uint256_mulmod(2 ** 255, 2, 6) == 4
    assert_tx_failed(lambda: c._uint256_mulmod(2, 2, 0))


def test_uint256_modmul(get_contract_with_gas_estimation):
    modexper = """
@external
def exponential(base: uint256, exponent: uint256, modulus: uint256) -> uint256:
    o: uint256 = 1
    for i in range(256):
        o = uint256_mulmod(o, o, modulus)
        if exponent & shift(1, 255 - i) != 0:
            o = uint256_mulmod(o, base, modulus)
    return o
    """

    c = get_contract_with_gas_estimation(modexper)
    assert c.exponential(3, 5, 100) == 43
    assert c.exponential(2, 997, 997) == 2


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_uint_literal(get_contract, assert_compile_failed, typ, lo, hi, bits):
    good_cases = [0, 1, 2, 3, hi // 2 - 1, hi // 2, hi // 2 + 1, hi - 1, hi]
    bad_cases = [-1, -2, -3, -hi // 2, -hi + 1, -hi]
    code_template = """
@external
def test() -> {typ}:
    o: {typ} = {val}
    return o
    """

    for val in good_cases:
        c = get_contract(code_template.format(typ=typ, val=val))
        assert c.test() == val

    for val in bad_cases:
        assert_compile_failed(lambda: get_contract(code_template.format(typ=typ, val=val)))
