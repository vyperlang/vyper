from decimal import ROUND_FLOOR, Decimal

import hypothesis
import pytest

from tests.utils import decimal_to_int
from vyper.compiler import compile_code
from vyper.exceptions import UnimplementedException
from vyper.utils import SizeLimits

DECIMAL_PLACES = 10
DECIMAL_RANGE = [Decimal("0." + "0" * d + "2") for d in range(0, DECIMAL_PLACES)]


def decimal_truncate(val, decimal_places=DECIMAL_PLACES, rounding=ROUND_FLOOR):
    q = "0"
    if decimal_places != 0:
        q += "." + "0" * decimal_places

    return val.quantize(Decimal(q), rounding=rounding)


def decimal_sqrt(val):
    return decimal_to_int(decimal_truncate(val.sqrt()))


def test_sqrt_literal(get_contract):
    code = """
import math

@external
def test() -> decimal:
    return math.sqrt(2.0)
    """
    c = get_contract(code)
    assert c.test() == decimal_sqrt(Decimal("2"))


# TODO: use parametrization here
def test_sqrt_variable(get_contract):
    code = """
import math

@external
def test(a: decimal) -> decimal:
    return math.sqrt(a)

@external
def test2() -> decimal:
    a: decimal = 44.001
    return math.sqrt(a)
    """

    c = get_contract(code)

    val = Decimal("33.33")
    assert c.test(decimal_to_int(val)) == decimal_sqrt(val)

    val = Decimal("0.1")
    assert c.test(decimal_to_int(val)) == decimal_sqrt(val)

    assert c.test(decimal_to_int("0.0")) == decimal_to_int("0.0")
    assert c.test2() == decimal_sqrt(Decimal("44.001"))


def test_sqrt_storage(get_contract):
    code = """
import math

s_var: decimal

@external
def test(a: decimal) -> decimal:
    self.s_var = a + 1.0
    return math.sqrt(self.s_var)

@external
def test2() -> decimal:
    self.s_var = 444.44
    return math.sqrt(self.s_var)
    """

    c = get_contract(code)
    val = Decimal("12.21")
    assert c.test(decimal_to_int(val)) == decimal_sqrt(val + 1)
    val = Decimal("100.01")
    assert c.test(decimal_to_int(val)) == decimal_sqrt(val + 1)
    assert c.test2() == decimal_sqrt(Decimal("444.44"))


def test_sqrt_inline_memory_correct(get_contract):
    code = """
import math

@external
def test(a: decimal) -> (decimal, decimal, decimal, decimal, decimal, String[100]):
    x: decimal = 1.0
    y: decimal = 2.0
    z: decimal = 3.0
    e: decimal = math.sqrt(a)
    f: String[100] = 'hello world'
    return a, x, y, z, e, f
    """

    c = get_contract(code)

    val = Decimal("2.1")
    assert c.test(decimal_to_int(val)) == (
        decimal_to_int(val),
        decimal_to_int("1"),
        decimal_to_int("2"),
        decimal_to_int("3"),
        decimal_sqrt(val),
        "hello world",
    )


@pytest.mark.parametrize("value", DECIMAL_RANGE)
def test_sqrt_sub_decimal_places(value, get_contract):
    code = """
import math

@external
def test(a: decimal) -> decimal:
    return math.sqrt(a)
    """

    c = get_contract(code)

    vyper_sqrt = c.test(decimal_to_int(value))
    actual_sqrt = decimal_sqrt(value)
    assert vyper_sqrt == actual_sqrt


@pytest.fixture(scope="module")
def sqrt_contract(get_contract):
    code = """
import math

@external
def test(a: decimal) -> decimal:
    return math.sqrt(a)
    """
    c = get_contract(code)
    return c


@pytest.mark.parametrize("value", [Decimal(0), Decimal(SizeLimits.MAX_INT128)])
def test_sqrt_bounds(sqrt_contract, value):
    vyper_sqrt = sqrt_contract.test(decimal_to_int(value))
    actual_sqrt = decimal_sqrt(value)
    assert vyper_sqrt == actual_sqrt


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.decimals(
        min_value=Decimal(0), max_value=Decimal(SizeLimits.MAX_INT128), places=DECIMAL_PLACES
    )
)
@hypothesis.example(value=Decimal(SizeLimits.MAX_INT128))
@hypothesis.example(value=Decimal(0))
# cf. GHSA-2p94-8669-xg86 for the following three examples:
@hypothesis.example(value=Decimal("0.9999999998"))
@hypothesis.example(value=Decimal("0.9999999997"))
@hypothesis.example(value=Decimal("1.1000000000"))
def test_sqrt_valid_range(sqrt_contract, value):
    vyper_sqrt = sqrt_contract.test(decimal_to_int(value))
    actual_sqrt = decimal_sqrt(value)
    assert vyper_sqrt == actual_sqrt


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.decimals(
        min_value=Decimal(SizeLimits.MIN_INT128), max_value=Decimal("-1E10"), places=DECIMAL_PLACES
    )
)
@hypothesis.example(value=Decimal(SizeLimits.MIN_INT128))
@hypothesis.example(value=Decimal("-1E10"))
def test_sqrt_invalid_range(tx_failed, sqrt_contract, value):
    with tx_failed():
        sqrt_contract.test(decimal_to_int(value))


def test_sqrt_eval_once(get_contract):
    code = """
import math

c: uint256

@internal
def some_decimal() -> decimal:
    self.c += 1
    return 1.0

@external
def foo() -> uint256:
    k: decimal = math.sqrt(self.some_decimal())
    return self.c
    """

    c = get_contract(code)
    assert c.foo() == 1


def test_use_old_sqrt_builtin(get_contract):
    code = """
import math

@external
def foo() -> decimal:
    return sqrt(2.0)
    """
    pattern = "The `sqrt` builtin was removed. Instead import module `math` and use `math.sqrt()"
    with pytest.raises(UnimplementedException, match=pattern):
        compile_code(code)
