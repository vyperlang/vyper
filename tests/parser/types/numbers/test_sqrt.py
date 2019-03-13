from decimal import (
    ROUND_FLOOR,
    Decimal,
)


def decimal_sqrt(val):
    return val.sqrt().quantize(
        Decimal('0.0000000000'),
        rounding=ROUND_FLOOR
    )


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
