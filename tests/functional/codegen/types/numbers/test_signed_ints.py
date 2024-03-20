import itertools
import operator
import random

import pytest

from vyper import compile_code
from vyper.exceptions import (
    InvalidOperation,
    OverflowException,
    TypeMismatch,
    ZeroDivisionException,
)
from vyper.semantics.types import IntegerT
from vyper.utils import evm_div, evm_mod

types = sorted(IntegerT.signeds())


@pytest.mark.parametrize("typ", types)
def test_exponent_base_zero(get_contract, tx_failed, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 0 ** x
    """
    lo, hi = typ.ast_bounds

    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(hi) == 0

    with tx_failed():
        c.foo(-1)
    with tx_failed():
        c.foo(lo)  # note: lo < 0


@pytest.mark.parametrize("typ", types)
def test_exponent_base_one(get_contract, tx_failed, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 1 ** x
    """
    lo, hi = typ.ast_bounds

    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(hi) == 1

    with tx_failed():
        c.foo(-1)
    with tx_failed():
        c.foo(lo)


def test_exponent_base_minus_one(get_contract):
    # #2986
    # NOTE!!! python order of precedence means -1 ** x != (-1) ** x
    code = """
@external
def foo(x: int256) -> int256:
    y: int256 = (-1) ** x
    return y
    """
    c = get_contract(code)
    for x in range(5):
        assert c.foo(x) == (-1) ** x


# TODO: make this test pass
@pytest.mark.parametrize("base", (0, 1))
def test_exponent_negative_power(get_contract, tx_failed, base):
    # #2985
    code = f"""
@external
def bar() -> int16:
    x: int16 = -2
    return {base} ** x
    """
    c = get_contract(code)
    # known bug: 2985
    with tx_failed():
        c.bar()


def test_exponent_min_int16(get_contract):
    # #2987
    code = """
@external
def foo() -> int16:
    x: int16 = -8
    y: int16 = x ** 5
    return y
    """
    c = get_contract(code)
    assert c.foo() == -(2**15)


@pytest.mark.parametrize("base,power", itertools.product((-2, -1, 0, 1, 2), (0, 1)))
def test_exponent_power_zero_one(get_contract, base, power):
    # #2989
    code = f"""
@external
def foo() -> int256:
    x: int256 = {base}
    return x ** {power}
    """
    c = get_contract(code)
    assert c.foo() == base**power


@pytest.mark.parametrize("typ", types)
def test_exponent(get_contract, tx_failed, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 4 ** x
    """
    lo, hi = typ.ast_bounds

    c = get_contract(code)

    test_cases = [0, 1, 3, 4, 126, 127, -1, lo, hi]
    for x in test_cases:
        if x * 2 >= typ.bits or x < 0:  # out of bounds
            with tx_failed():
                c.foo(x)
        else:
            assert c.foo(x) == 4**x


@pytest.mark.parametrize("typ", types)
def test_negative_nums(get_contract_with_gas_estimation, typ):
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


@pytest.mark.parametrize("typ", types)
def test_num_bound(tx_failed, get_contract_with_gas_estimation, typ):
    lo, hi = typ.ast_bounds

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
    with tx_failed():
        c._num_add(hi, 1)
    with tx_failed():
        c._num_sub(lo, 1)
    with tx_failed():
        c._num_add(hi - 1, 2)
    with tx_failed():
        c._num_sub(lo + 1, 2)
    assert c._num_max() == hi
    assert c._num_min() == lo

    with tx_failed():
        c._num_add3(hi, 1, -1)
    assert c._num_add3(hi, -1, 1) == hi - 1 + 1
    with tx_failed():
        c._num_add3(lo, -1, 1)
    assert c._num_add3(lo, 1, -1) == lo + 1 - 1


@pytest.mark.parametrize("typ", types)
def test_overflow_out_of_range(get_contract, typ):
    code = f"""
@external
def num_sub() -> {typ}:
    return 1-2**{typ.bits}
    """

    exc = OverflowException if typ.bits == 256 else TypeMismatch
    with pytest.raises(exc):
        compile_code(code)


ARITHMETIC_OPS = {
    "+": operator.add,
    "-": operator.sub,
    "*": operator.mul,
    "//": evm_div,
    "%": evm_mod,
}


@pytest.mark.parametrize("op", sorted(ARITHMETIC_OPS.keys()))
@pytest.mark.parametrize("typ", types)
@pytest.mark.fuzzing
def test_arithmetic_thorough(get_contract, tx_failed, op, typ):
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
    lo, hi = typ.ast_bounds

    fns = {"+": operator.add, "-": operator.sub, "*": operator.mul, "//": evm_div, "%": evm_mod}
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
        hi - 1,
        hi,
    ]
    xs = special_cases.copy()
    ys = special_cases.copy()

    # note: (including special cases, roughly 8k cases total generated)

    NUM_CASES = 5
    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    xs += [random.randrange(lo, hi) for _ in range(NUM_CASES)]
    ys += [random.randrange(lo, hi) for _ in range(NUM_CASES)]

    # edge cases that are tricky to reason about and MUST be tested
    assert lo in xs and -1 in ys

    for x, y in itertools.product(xs, ys):
        expected = fn(x, y)
        in_bounds = lo <= expected <= hi

        # safediv and safemod disallow divisor == 0
        div_by_zero = y == 0 and op in ("//", "%")

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
            with tx_failed():
                c.foo(x, y)
            with pytest.raises(ZeroDivisionException):
                compile_code(code_2)
            with tx_failed():
                get_contract(code_3).foo(y)
            with pytest.raises(ZeroDivisionException):
                compile_code(code_4)
        else:
            with tx_failed():
                c.foo(x, y)
            with tx_failed():
                get_contract(code_2).foo(x)
            with tx_failed():
                get_contract(code_3).foo(y)
            with pytest.raises((TypeMismatch, OverflowException)):
                compile_code(code_4)


COMPARISON_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}


@pytest.mark.parametrize("op", sorted(COMPARISON_OPS.keys()))
@pytest.mark.parametrize("typ", types)
@pytest.mark.fuzzing
def test_comparators(get_contract, op, typ):
    code_1 = f"""
@external
def foo(x: {typ}, y: {typ}) -> bool:
    return x {op} y
    """

    lo, hi = typ.ast_bounds

    fn = COMPARISON_OPS[op]
    c = get_contract(code_1)

    # note: constant folding is tested in tests/unit/ast/nodes
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
        hi - 1,
        hi,
    ]

    xs = special_cases.copy()
    ys = special_cases.copy()

    for x, y in itertools.product(xs, ys):
        expected = fn(x, y)
        assert c.foo(x, y) is expected


@pytest.mark.parametrize("typ", types)
def test_negation(get_contract, tx_failed, typ):
    code = f"""
@external
def foo(a: {typ}) -> {typ}:
    return -a
    """

    lo, hi = typ.ast_bounds

    c = get_contract(code)

    assert c.foo(hi) == lo + 1
    assert c.foo(-1) == 1
    assert c.foo(1) == -1
    assert c.foo(0) == 0
    assert c.foo(2) == -2
    assert c.foo(-2) == 2

    with tx_failed():
        c.foo(lo)


@pytest.mark.parametrize("typ", types)
@pytest.mark.parametrize("op", ["/"])
def test_invalid_ops(get_contract, assert_compile_failed, typ, op):
    code = f"""
@external
def foo(x: {typ}, y: {typ}) -> {typ}:
    return x {op} y
    """
    assert_compile_failed(lambda: get_contract(code), InvalidOperation)


@pytest.mark.parametrize("typ", types)
@pytest.mark.parametrize("op", ["not"])
def test_invalid_unary_ops(typ, op):
    code = f"""
@external
def foo(a: {typ}) -> {typ}:
    return {op} a
    """
    with pytest.raises(InvalidOperation):
        compile_code(code)


def test_binop_nested_intermediate_underflow():
    code = """
@external
def foo():
    a: int256 = -2**255 * 2 - 10 + 100
    """
    with pytest.raises(TypeMismatch):
        compile_code(code)


def test_invalid_div():
    code = """
@external
def foo():
    a: int256 = -5 / 9
    """
    with pytest.raises(InvalidOperation) as e:
        compile_code(code)

    assert e.value._hint == "did you mean `-5 // 9`?"
