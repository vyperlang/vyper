import itertools
import operator
import random

import pytest

from vyper.codegen.types.types import SIGNED_INTEGER_TYPES, parse_integer_typeinfo
from vyper.exceptions import InvalidType, OverflowException
from vyper.utils import SizeLimits, evm_div, evm_mod, int_bounds

PARAMS = []
for t in sorted(SIGNED_INTEGER_TYPES):
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
    assert c.foo(-1) == 0

    assert c.foo(lo) == 0
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
    assert c.foo(-1) == 1
    assert c.foo(lo) == 1
    assert c.foo(hi) == 1


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_exponent(get_contract, assert_tx_failed, typ, lo, hi, bits):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 4 ** x
    """
    c = get_contract(code)

    test_cases = [0, 1, 3, 4, 126, 127, -1, lo, hi]
    for x in test_cases:
        if x * 2 >= bits or x < 0:  # out of bounds
            assert_tx_failed(lambda: c.foo(x))
        else:
            assert c.foo(x) == 4 ** x


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_num_divided_by_num(get_contract_with_gas_estimation, typ, lo, hi, bits):
    code = f"""
@external
def foo(inp: {typ}) -> {typ}:
    y: {typ} = 5/inp
    return y
    """
    c = get_contract_with_gas_estimation(code)
    assert c.foo(2) == 2
    assert c.foo(5) == 1
    assert c.foo(10) == 0
    assert c.foo(50) == 0


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_negative_nums(get_contract_with_gas_estimation, typ, lo, hi, bits):
    negative_nums_code = f"""
@external
def negative_one() -> {typ}:
    return -1

@external
def negative_three() -> {typ}:
    return -(1+2)

@external
def negative_four() -> {typ}:
    a: {typ} = 2
    return -(a+2)
    """

    c = get_contract_with_gas_estimation(negative_nums_code)
    assert c.negative_one() == -1
    assert c.negative_three() == -3
    assert c.negative_four() == -4


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_num_bound(assert_tx_failed, get_contract_with_gas_estimation, typ, lo, hi, bits):
    num_bound_code = f"""
@external
def _num(x: {typ}) -> {typ}:
    return x

@external
def _num_add(x: {typ}, y: {typ}) -> {typ}:
    return x + y

@external
def _num_sub(x: {typ}, y: {typ}) -> {typ}:
    return x - y

@external
def _num_add3(x: {typ}, y: {typ}, z: {typ}) -> {typ}:
    return x + y + z

@external
def _num_max() -> {typ}:
    return {hi}

@external
def _num_min() -> {typ}:
    return {lo}
    """

    c = get_contract_with_gas_estimation(num_bound_code)

    assert c._num_add(hi, 0) == hi
    assert c._num_sub(lo, 0) == lo
    assert c._num_add(hi - 1, 1) == hi
    assert c._num_sub(lo + 1, 1) == lo
    assert_tx_failed(lambda: c._num_add(hi, 1))
    assert_tx_failed(lambda: c._num_sub(lo, 1))
    assert_tx_failed(lambda: c._num_add(hi - 1, 2))
    assert_tx_failed(lambda: c._num_sub(lo + 1, 2))
    assert c._num_max() == hi
    assert c._num_min() == lo

    assert_tx_failed(lambda: c._num_add3(hi, 1, -1))
    assert c._num_add3(hi, -1, 1) == hi - 1 + 1
    assert_tx_failed(lambda: c._num_add3(lo, -1, 1))
    assert c._num_add3(lo, 1, -1) == lo + 1 - 1


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_overflow_out_of_range(get_contract, assert_compile_failed, typ, lo, hi, bits):
    code = f"""
@external
def num_sub() -> {typ}:
    return 1-2**{bits}
    """

    if bits == 256:
        assert_compile_failed(lambda: get_contract(code), OverflowException)
    else:
        assert_compile_failed(lambda: get_contract(code), InvalidType)


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_add_3(get_contract, assert_tx_failed, typ, lo, hi, bits):
    code = f"""
@external
def add_hi(i: {typ}) -> {typ}:
    return {hi} + i

@external
def add_lo(i: {typ}) -> {typ}:
    return {lo} + i
    """
    c = get_contract(code)

    assert c.add_hi(0) == hi
    assert c.add_hi(-1) == hi - 1

    assert_tx_failed(lambda: c.add_hi(1))
    assert_tx_failed(lambda: c.add_hi(2))

    assert c.add_lo(0) == lo
    assert c.add_lo(1) == lo + 1

    assert_tx_failed(lambda: c.add_lo(-1))
    assert_tx_failed(lambda: c.add_lo(-2))


@pytest.mark.parametrize("op", ["+", "-", "*", "/", "%"])
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

    fns = {"+": operator.add, "-": operator.sub, "*": operator.mul, "/": evm_div, "%": evm_mod}
    fn = fns[op]

    c = get_contract(code_1)

    # TODO refactor to use fixtures
    special_cases = [
        lo,
        lo + 1,
        lo // 2,
        lo // 2 - 1,
        lo // 2 + 1,
        -3,
        -2,
        -1,
        0,
        1,
        2,
        3,
        hi // 2 - 1,
        hi // 2,
        hi // 2 + 1,
        (hi + 1) // 2,
        hi - 1,
        hi,
    ]
    xs = special_cases.copy()
    ys = special_cases.copy()

    # note: (including special cases, roughly 8k cases total generated)

    NUM_CASES = 15
    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    xs = [random.randrange(lo, hi) for _ in range(NUM_CASES)]
    ys = [random.randrange(lo, hi) for _ in range(NUM_CASES)]

    for (x, y) in itertools.product(xs, ys):
        expected = fn(x, y)
        ok = SizeLimits.in_bounds(typ, expected)
        # safediv and safemod disallow divisor == 0
        ok &= not (y == 0 and op in ("/", "%"))

        code_2 = code_2_template.format(typ=typ, op=op, y=y)
        code_3 = code_3_template.format(typ=typ, op=op, x=x)
        code_4 = code_4_template.format(typ=typ, op=op, x=x, y=y)

        if SizeLimits.in_bounds(typ, expected):
            assert c.foo(x, y) == expected
            assert get_contract(code_2).foo(x) == expected
            assert get_contract(code_3).foo(y) == expected
            assert get_contract(code_4).foo() == expected
        else:
            assert_tx_failed(lambda: c.foo(x, y))
            assert_tx_failed(lambda: get_contract(code_2).foo(x))
            assert_tx_failed(lambda: get_contract(code_3).foo(y))
            assert_compile_failed(lambda: get_contract(code_4), InvalidType)


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_negation(get_contract, assert_tx_failed, typ, lo, hi, bits):
    code = f"""
@external
def foo(a: {typ}) -> {typ}:
    return -a
    """

    c = get_contract(code)

    assert c.foo(hi) == lo + 1
    assert c.foo(-1) == 1
    assert c.foo(1) == -1
    assert c.foo(0) == 0
    assert c.foo(2) == -2
    assert c.foo(-2) == 2

    assert_tx_failed(lambda: c.foo(lo))


@pytest.mark.parametrize("typ,lo,hi,bits", PARAMS)
def test_literal_negative_int(get_contract, assert_tx_failed, typ, lo, hi, bits):
    code = f"""
@external
def sub_one(a: {typ}) -> {typ}:
    return a + -1

@external
def add_one(a: {typ}) -> {typ}:
    return a - -1
    """

    c = get_contract(code)

    assert c.sub_one(23) == 22
    assert c.add_one(23) == 24

    assert c.sub_one(-23) == -24
    assert c.add_one(-23) == -22

    assert c.sub_one(lo + 1) == lo
    assert c.add_one(hi - 1) == hi

    assert_tx_failed(lambda: c.sub_one(lo))
    assert_tx_failed(lambda: c.add_one(hi))
