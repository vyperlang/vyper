import itertools
import operator
import random

import pytest

from vyper.exceptions import InvalidOperation, InvalidType, OverflowException, ZeroDivisionException
from vyper.semantics.types import IntegerT
from vyper.utils import evm_div, evm_mod

types = sorted(IntegerT.unsigneds())


@pytest.mark.parametrize("typ", types)
def test_exponent_base_zero(get_contract, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 0 ** x
    """
    lo, hi = typ.ast_bounds
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 0
    assert c.foo(42) == 0
    assert c.foo(hi) == 0


@pytest.mark.parametrize("typ", types)
def test_exponent_base_one(get_contract, typ):
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return 1 ** x
    """
    lo, hi = typ.ast_bounds
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(hi) == 1


@pytest.mark.parametrize("typ", types)
def test_exponent_power_zero(get_contract, typ):
    # #2984
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return x ** 0
    """
    lo, hi = typ.ast_bounds
    c = get_contract(code)
    assert c.foo(0) == 1
    assert c.foo(1) == 1
    assert c.foo(42) == 1
    assert c.foo(hi) == 1


@pytest.mark.parametrize("typ", types)
def test_exponent_power_one(get_contract, typ):
    # #2984
    code = f"""
@external
def foo(x: {typ}) -> {typ}:
    return x ** 1
    """
    lo, hi = typ.ast_bounds
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
@pytest.mark.parametrize("typ", types)
@pytest.mark.fuzzing
def test_arithmetic_thorough(get_contract, assert_tx_failed, assert_compile_failed, op, typ):
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

    fn = ARITHMETIC_OPS[op]
    c = get_contract(code_1)

    lo, hi = typ.ast_bounds
    bits = typ.bits

    special_cases = [0, 1, 2, 3, hi // 2 - 1, hi // 2, hi // 2 + 1, hi - 2, hi - 1, hi]
    xs = special_cases.copy()
    ys = special_cases.copy()
    NUM_CASES = 5
    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    xs += [random.randrange(lo, hi) for _ in range(NUM_CASES)]
    ys += [random.randrange(lo, hi) for _ in range(NUM_CASES)]

    # mirror signed integer tests
    assert 2 ** (bits - 1) in xs and (2**bits) - 1 in ys

    for x, y in itertools.product(xs, ys):
        expected = fn(x, y)

        in_bounds = lo <= expected <= hi
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
@pytest.mark.parametrize("typ", types)
@pytest.mark.fuzzing
def test_comparators(get_contract, op, typ):
    code_1 = f"""
@external
def foo(x: {typ}, y: {typ}) -> bool:
    return x {op} y
    """

    fn = COMPARISON_OPS[op]
    c = get_contract(code_1)

    lo, hi = typ.ast_bounds

    # note: constant folding is tested in tests/ast/folding

    special_cases = [0, 1, 2, 3, hi // 2 - 1, hi // 2, hi // 2 + 1, hi - 2, hi - 1, hi]
    xs = special_cases.copy()
    ys = special_cases.copy()

    for x, y in itertools.product(xs, ys):
        expected = fn(x, y)
        assert c.foo(x, y) is expected


@pytest.mark.parametrize("typ", types)
def test_uint_literal(get_contract, assert_compile_failed, typ):
    lo, hi = typ.ast_bounds

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


@pytest.mark.parametrize("typ", types)
@pytest.mark.parametrize("op", ["not", "-"])
def test_invalid_unary_ops(get_contract, assert_compile_failed, typ, op):
    code = f"""
@external
def foo(a: {typ}) -> {typ}:
    return {op} a
    """
    assert_compile_failed(lambda: get_contract(code), InvalidOperation)
