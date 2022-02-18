import pytest
import operator
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vyper.utils import BASE_TYPES, DECIMAL_DIVISOR, int_bounds
from vyper.codegen.types.types import BaseType, parse_integer_typeinfo

# TODO something less janky
integer_types = sorted([t for t in BASE_TYPES if "int" in t])


# interpret a signed EVM word as an unsigned word
def _as_unsigned(x, bits):
    if x < 0:
        return x + 2**bits
    return x


# interpret an unsigned EVM word as a signed word
def _as_signed(x, bits):
    if x > (2**(bits-1)) - 1:
        return x - 2**bits
    return x


# TODO this is probably more broadly useful
def _int_strategy(typname):
    int_info = parse_integer_typeinfo(typname)
    lo, hi = int_bounds(int_info.is_signed, int_info.bits)
    return st.integers(min_value=lo, max_value=hi)

def _evm_div(x, y):
    if y == 0:
        return 0
    # note round-to-zero behavior compared to floordiv
    return int(x / y)

@pytest.mark.parametrize("typ", integer_types)
@pytest.mark.parametrize("op", ["add", "sub", "mul", "div"])
@given(st.data())
def test_unsafe_op_int(get_contract, typ, op, data):
    code = f"""
@external
def foo(x: {typ}, y: {typ}) -> {typ}:
    return unsafe_{op}(x, y)
    """
    fns = { "add": operator.add, "sub": operator.sub, "mul": operator.mul, "div": _evm_div }
    fn = fns[op]

    int_info = parse_integer_typeinfo(typ)

    x = data.draw(_int_strategy(typ))
    y = data.draw(_int_strategy(typ))

    c = get_contract(code)
    mod_bound = 2**int_info.bits
    if int_info.is_signed:
        assert c.foo(x, y) == _as_signed(fn(x, y) % mod_bound, int_info.bits)
    else:
        assert c.foo(x, y) == _as_unsigned(fn(x, y) % mod_bound, int_info.bits)
