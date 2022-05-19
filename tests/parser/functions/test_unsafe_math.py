import itertools
import operator
import random

import pytest

from vyper.codegen.types.types import INTEGER_TYPES, parse_integer_typeinfo
from vyper.utils import evm_div, int_bounds, unsigned_to_signed

# TODO something less janky
integer_types = sorted(list(INTEGER_TYPES))


@pytest.mark.parametrize("typ", integer_types)
@pytest.mark.parametrize("op", ["add", "sub", "mul", "div"])
@pytest.mark.fuzzing
def test_unsafe_op_int(get_contract, typ, op):
    contract_1 = f"""
@external
def foo(x: {typ}, y: {typ}) -> {typ}:
    return unsafe_{op}(x, y)
    """

    contract_2 = """
@external
def foo(x: {typ}) -> {typ}:
    return unsafe_{op}(x, {literal})
    """

    fns = {"add": operator.add, "sub": operator.sub, "mul": operator.mul, "div": evm_div}
    fn = fns[op]

    int_info = parse_integer_typeinfo(typ)
    c1 = get_contract(contract_1)

    lo, hi = int_bounds(int_info.is_signed, int_info.bits)
    # (roughly 8k cases total generated)
    # TODO refactor to use fixtures
    NUM_CASES = 15
    xs = [random.randrange(lo, hi) for _ in range(NUM_CASES)]
    ys = [random.randrange(lo, hi) for _ in range(NUM_CASES)]

    mod_bound = 2 ** int_info.bits

    # poor man's fuzzing - hypothesis doesn't make it easy
    # with the parametrized strategy
    if int_info.is_signed:
        xs += [lo, lo + 1, -1, 0, 1, hi - 1, hi]
        ys += [lo, lo + 1, -1, 0, 1, hi - 1, hi]
        for (x, y) in itertools.product(xs, ys):
            expected = unsigned_to_signed(fn(x, y) % mod_bound, int_info.bits)

            assert c1.foo(x, y) == expected

            c2 = get_contract(contract_2.format(typ=typ, op=op, literal=y))
            assert c2.foo(x) == expected

    else:
        # 0x80 has some weird properties, like
        # it's a fixed point of multiplication by 0xFF
        fixed_pt = 2 ** (int_info.bits - 1)
        xs += [0, 1, hi - 1, hi, fixed_pt]
        ys += [0, 1, hi - 1, hi, fixed_pt]
        for (x, y) in itertools.product(xs, ys):
            expected = fn(x, y) % mod_bound
            assert c1.foo(x, y) == expected

            c2 = get_contract(contract_2.format(typ=typ, op=op, literal=y))
            assert c2.foo(x) == expected
