from decimal import (
    ROUND_FLOOR,
    Decimal,
)

import pytest

DECIMAL_PLACES = 10
DECIMAL_RANGE = [
    Decimal('0.' + '0' * d + '2')
    for d in range(0, DECIMAL_PLACES)
]


def decimal_sqrt(val, decimal_places=DECIMAL_PLACES, rounding=ROUND_FLOOR):
    q = '0'
    if decimal_places != 0:
        q += '.' + '0' * decimal_places
    return val.sqrt().quantize(Decimal(q), rounding=rounding)


def test_sqrt_literal(get_contract_with_gas_estimation):
    code = """
@public
def test() -> decimal:
    return sqrt(2.0)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test() == decimal_sqrt(Decimal('2'))


def test_sqrt_variable(get_contract_with_gas_estimation):
    code = """
@public
def test(a: decimal) -> decimal:
    return sqrt(a)

@public
def test2() -> decimal:
    a: decimal = 44.001
    return sqrt(a)
    """

    c = get_contract_with_gas_estimation(code)

    val = Decimal('33.33')
    assert c.test(val) == decimal_sqrt(val)

    val = Decimal('0.1')
    assert c.test(val) == decimal_sqrt(val)

    assert c.test(Decimal('0.0')) == Decimal('0.0')
    assert c.test2() == decimal_sqrt(Decimal('44.001'))


def test_sqrt_storage(get_contract_with_gas_estimation):
    code = """
s_var: decimal

@public
def test(a: decimal) -> decimal:
    self.s_var = a + 1.0
    return sqrt(self.s_var)

@public
def test2() -> decimal:
    self.s_var = 444.44
    return sqrt(self.s_var)
    """

    c = get_contract_with_gas_estimation(code)
    val = Decimal('12.21')
    assert c.test(val) == decimal_sqrt(val + 1)
    val = Decimal('100.01')
    assert c.test(val) == decimal_sqrt(val + 1)
    assert c.test2() == decimal_sqrt(Decimal('444.44'))


def test_sqrt_inline_memory_correct(get_contract_with_gas_estimation):
    code = """
@public
def test(a: decimal) -> (decimal, decimal, decimal, decimal, decimal, string[100]):
    b: decimal = 1.0
    c: decimal = 2.0
    d: decimal = 3.0
    e: decimal = sqrt(a)
    f: string[100] = 'hello world'
    return a, b, c, d, e, f
    """

    c = get_contract_with_gas_estimation(code)

    val = Decimal('2.1')
    assert c.test(val) == [
        val,
        Decimal('1'),
        Decimal('2'),
        Decimal('3'),
        decimal_sqrt(val),
        'hello world'
    ]


@pytest.mark.parametrize('sub_val', DECIMAL_RANGE)
def test_sqrt_sub_decimal_places(sub_val, get_contract):
    code = """
@public
def test(a: decimal) -> decimal:
    return sqrt(a)
    """

    c = get_contract(code)

    vyper_sqrt = c.test(sub_val)
    actual_sqrt = decimal_sqrt(sub_val)
    assert vyper_sqrt == actual_sqrt
