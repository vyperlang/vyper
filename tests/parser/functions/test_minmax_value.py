import pytest

from vyper.codegen.types import (
    DECIMAL_TYPES,
    INTEGER_TYPES,
    parse_decimal_info,
    parse_integer_typeinfo,
)
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
