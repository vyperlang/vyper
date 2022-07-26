import pytest

from vyper.codegen.types import (
    DECIMAL_TYPES,
    INTEGER_TYPES,
    parse_decimal_info,
    parse_integer_typeinfo,
)
from vyper.exceptions import InvalidType, OverflowException
from vyper.utils import int_bounds


@pytest.mark.parametrize("typ", sorted(INTEGER_TYPES))
@pytest.mark.parametrize("op", ("min_value", "max_value"))
def test_minmax_value_int(get_contract, op, typ):
    code = f"""
@external
def foo() -> {typ}:
    return {op}({typ})
    """
    c = get_contract(code)

    typ_info = parse_integer_typeinfo(typ)
    (lo, hi) = int_bounds(typ_info.is_signed, typ_info.bits)
    if op == "min_value":
        assert c.foo() == lo
    elif op == "max_value":
        assert c.foo() == hi


@pytest.mark.parametrize("typ", sorted(INTEGER_TYPES))
def test_minmax_value_int_oob(get_contract, assert_compile_failed, typ):
    upper = f"""
@external
def foo():
    a: {typ} = max_value({typ}) + 1
    """

    lower = f"""
@external
def foo():
    a: {typ} = min_value({typ}) - 1
    """

    if typ == "uint256":
        assert_compile_failed(lambda: get_contract(upper), OverflowException)
    else:
        assert_compile_failed(lambda: get_contract(upper), InvalidType)

    if typ == "int256":
        assert_compile_failed(lambda: get_contract(lower), OverflowException)
    else:
        assert_compile_failed(lambda: get_contract(lower), InvalidType)


@pytest.mark.parametrize("typ", sorted(DECIMAL_TYPES))
@pytest.mark.parametrize("op", ("min_value", "max_value"))
def test_minmax_value_decimal(get_contract, op, typ):
    code = f"""
@external
def foo() -> {typ}:
    return {op}({typ})
    """
    c = get_contract(code)

    typ_info = parse_decimal_info(typ)
    (lo, hi) = typ_info.decimal_bounds
    if op == "min_value":
        assert c.foo() == lo
    elif op == "max_value":
        assert c.foo() == hi


@pytest.mark.parametrize("typ", sorted(DECIMAL_TYPES))
def test_minmax_value_decimal_oob(get_contract, assert_compile_failed, typ):
    upper = f"""
@external
def foo():
    a: {typ} = max_value({typ}) + 1e-10
    """

    lower = f"""
@external
def foo():
    a: {typ} = min_value({typ}) - 1e-10
    """

    assert_compile_failed(lambda: get_contract(upper), OverflowException)
    assert_compile_failed(lambda: get_contract(lower), OverflowException)
