from vyper.exceptions import TypeMismatchException
from decimal import Decimal


def test_modulo(get_contract_with_gas_estimation):
    code = """
@public
def num_modulo_num() -> int128:
    return 1 % 2

@public
def decimal_modulo_decimal() -> decimal:
    return 1.5 % .33

@public
def decimal_modulo_num() -> decimal:
    return .5 % 1.0


@public
def num_modulo_decimal() -> decimal:
    return 1.5 % 1.0
"""
    c = get_contract_with_gas_estimation(code)
    assert c.num_modulo_num() == 1
    assert c.decimal_modulo_decimal() == Decimal('.18')
    assert c.decimal_modulo_num() == Decimal('.5')
    assert c.num_modulo_decimal() == Decimal('.5')


def test_modulo_with_different_units(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
units: {
    currency_value: "a currency amount"
}
@public
def foo(a: int128(currency_value), b: int128):
    x: int128 = a % b
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)


def test_modulo_with_positional_input(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(a: int128(sec, positional), b: int128):
    x: int128 = a % b
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)


def test_modulo_with_input_of_zero(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a % b
"""
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(Decimal('1'), Decimal('0')))
