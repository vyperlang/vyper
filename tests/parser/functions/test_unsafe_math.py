import pytest
import itertools
import random
import operator

from vyper.utils import BASE_TYPES, DECIMAL_DIVISOR, int_bounds, evm_div
from vyper.codegen.types.types import BaseType, parse_integer_typeinfo

# TODO something less janky
integer_types = sorted([t for t in BASE_TYPES if "int" in t])


def _as_signed(x, bits):
    if x > (2 ** (bits - 1)) - 1:
        return x - 2 ** bits
    return x


@pytest.mark.parametrize("typ", integer_types)
@pytest.mark.parametrize("op", ["add", "sub", "mul", "div"])
@pytest.mark.fuzzing
def test_unsafe_op_int(get_contract, typ, op):
    code = f"""
@external
def foo(x: {typ}, y: {typ}) -> {typ}:
    return unsafe_{op}(x, y)
    """
    fns = {"add": operator.add, "sub": operator.sub, "mul": operator.mul, "div": evm_div}
    fn = fns[op]

    int_info = parse_integer_typeinfo(typ)
    c = get_contract(code)

    lo, hi = int_bounds(int_info.is_signed, int_info.bits)
    xs = [random.randrange(lo, hi) for _ in range(100)]
    ys = [random.randrange(lo, hi) for _ in range(100)]

    mod_bound = 2 ** int_info.bits

    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    if int_info.is_signed:
        xs += [lo, -1, 0, 1, hi]
        ys += [lo, -1, 0, 1, hi]
        for (x, y) in itertools.product(xs, ys):
            expected = _as_signed(fn(x, y) % mod_bound, int_info.bits)
            assert c.foo(x, y) == expected
    else:
        xs += [0, 1, hi - 1, hi]
        ys += [0, 1, hi - 1, hi]
        for (x, y) in itertools.product(xs, ys):
            assert c.foo(x, y) == fn(x, y) % mod_bound
