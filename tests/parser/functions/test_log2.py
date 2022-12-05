from decimal import ROUND_FLOOR, Decimal

import hypothesis
import pytest
from eth_tester.exceptions import TransactionFailed

from vyper.utils import SizeLimits

DECIMAL_PLACES = 10
DECIMAL_RANGE = [Decimal("0." + "0" * d + "2") for d in range(0, DECIMAL_PLACES)]


def decimal_truncate(val, decimal_places=DECIMAL_PLACES, rounding=ROUND_FLOOR):
    q = "0"
    if decimal_places != 0:
        q += "." + "0" * decimal_places

    return val.quantize(Decimal(q), rounding=rounding)


CONVERT_LOG10_2 = Decimal(2).log10()


def decimal_log2(val):
    # Decimal only has log10; convert to log2.
    ret = val.log10() / CONVERT_LOG10_2
    return decimal_truncate(ret)


def test_log2_literal(get_contract_with_gas_estimation):
    code = """
@external
def test() -> decimal:
    return log2(3.0)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test() == decimal_log2(Decimal("3"))


def test_log2_variable(get_contract_with_gas_estimation):
    code = """
@external
def test(a: decimal) -> decimal:
    return log2(a)

@external
def test2() -> decimal:
    a: decimal = 10797662668.411692
    return log2(a)
    """

    c = get_contract_with_gas_estimation(code)

    val = Decimal("33.33")
    assert c.test(val) == decimal_log2(val)

    val = Decimal("0.1")
    assert c.test(val) == decimal_log2(val)

    assert c.test(Decimal("1.0")) == Decimal("0.0")
    assert c.test2() == Decimal("33.33")


def test_log2_storage(get_contract_with_gas_estimation):
    code = """
s_var: decimal

@external
def test(a: decimal) -> decimal:
    self.s_var = a + 1.0
    return log2(self.s_var)

@external
def test2() -> decimal:
    self.s_var = 444.44
    return log2(self.s_var)
    """

    c = get_contract_with_gas_estimation(code)
    val = Decimal("12.21")
    assert c.test(val) == decimal_log2(val + 1)
    val = Decimal("100.01")
    assert c.test(val) == decimal_log2(val + 1)
    assert c.test2() == decimal_log2(Decimal("444.44"))


def test_log2_inline_memory_correct(get_contract_with_gas_estimation):
    code = """
@external
def test(a: decimal) -> (decimal, decimal, decimal, decimal, decimal, String[100]):
    x: decimal = 1.0
    y: decimal = 2.0
    z: decimal = 3.0
    e: decimal = log2(a)
    f: String[100] = 'hello world'
    return a, x, y, z, e, f
    """

    c = get_contract_with_gas_estimation(code)

    val = Decimal("2.1")
    assert c.test(val) == [
        val,
        Decimal("1"),
        Decimal("2"),
        Decimal("3"),
        decimal_log2(val),
        "hello world",
    ]


@pytest.mark.parametrize("value", DECIMAL_RANGE)
def test_log2_sub_decimal_places(value, get_contract):
    code = """
@external
def test(a: decimal) -> decimal:
    return log2(a)
    """

    c = get_contract(code)

    vyper_log2 = c.test(value)
    actual_log2 = decimal_log2(value)
    assert vyper_log2 == actual_log2


@pytest.fixture(scope="module")
def log2_contract(get_contract_module):
    code = """
@external
def test(a: decimal) -> decimal:
    return log2(a)
    """
    c = get_contract_module(code)
    return c


@pytest.mark.parametrize("value", [Decimal(0), Decimal(SizeLimits.MAX_INT128)])
def test_log2_bounds(log2_contract, value):
    vyper_log2 = log2_contract.test(value)
    actual_log2 = decimal_log2(value)
    assert vyper_log2 == actual_log2


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.decimals(
        min_value=Decimal(0), max_value=Decimal(SizeLimits.MAX_INT128), places=DECIMAL_PLACES
    )
)
@hypothesis.example(Decimal(SizeLimits.MAX_INT128))
@hypothesis.example(Decimal(0))
@hypothesis.settings(deadline=1000)
def test_log2_valid_range(log2_contract, value):
    vyper_log2 = log2_contract.test(value)
    actual_log2 = decimal_log2(value)
    assert vyper_log2 == actual_log2


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.decimals(
        min_value=Decimal(SizeLimits.MIN_INT128),
        max_value=Decimal(1) - Decimal("1E-10"),
        places=DECIMAL_PLACES,
    )
)
@hypothesis.settings(deadline=400)
@hypothesis.example(Decimal(SizeLimits.MIN_INT128))
@hypothesis.example(Decimal(1) - Decimal("1E-10"))
def test_log2_invalid_range(log2_contract, value):
    with pytest.raises(TransactionFailed):
        log2_contract.test(value)
