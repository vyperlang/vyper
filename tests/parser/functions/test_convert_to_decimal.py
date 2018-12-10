from decimal import Decimal


def test_convert_to_decimal_units(get_contract, assert_tx_failed):
    code = """
units: {
    meter: "Meter"
}

@public
def test() -> decimal(meter):
    a: decimal(meter) = convert(5001, decimal)
    return a

@public
def test2() -> decimal(meter):
    b: int128(meter) = 1234
    a: decimal(meter) = convert(b, decimal)
    return a
    """

    c = get_contract(code)
    assert c.test() == Decimal('5001')
    assert c.test2() == Decimal('1234')


def test_convert_from_int128(get_contract_with_gas_estimation):
    code = """
a: int128
b: decimal

@public
def int128_to_decimal(inp: int128) -> (decimal, decimal, decimal):
    self.a = inp
    memory: decimal = convert(inp, decimal)
    storage: decimal = convert(self.a, decimal)
    literal: decimal = convert(1, decimal)
    return  memory, storage, literal
"""
    c = get_contract_with_gas_estimation(code)
    assert c.int128_to_decimal(1) == [1.0, 1.0, 1.0]


def test_convert_from_uint256(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test_variable() -> bool:
    a: uint256 = 1000
    return convert(a, decimal) == 1000.0

@public
def test_passed_variable(a: uint256) -> decimal:
    return convert(a, decimal)
    """

    c = get_contract_with_gas_estimation(code)

    assert c.test_variable() is True
    assert c.test_passed_variable(256) == 256
    max_decimal = (2**127 - 1)
    assert c.test_passed_variable(max_decimal) == Decimal(max_decimal)
    assert_tx_failed(lambda: c.test_passed_variable(max_decimal + 1))
