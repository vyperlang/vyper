from decimal import Decimal

import pytest

from vyper.exceptions import ZeroDivisionException


def test_modulo(get_contract_with_gas_estimation):
    code = """
@external
def num_modulo_num() -> int128:
    return 1 % 2

@external
def decimal_modulo_decimal() -> decimal:
    return 1.5 % .33

@external
def decimal_modulo_num() -> decimal:
    return .5 % 1.0


@external
def num_modulo_decimal() -> decimal:
    return 1.5 % 1.0
"""
    c = get_contract_with_gas_estimation(code)
    assert c.num_modulo_num() == 1
    assert c.decimal_modulo_decimal() == Decimal(".18")
    assert c.decimal_modulo_num() == Decimal(".5")
    assert c.num_modulo_decimal() == Decimal(".5")


def test_modulo_with_input_of_zero(tx_failed, get_contract_with_gas_estimation):
    code = """
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a % b
"""
    c = get_contract_with_gas_estimation(code)
    with tx_failed():
        c.foo(Decimal("1"), Decimal("0"))


def test_literals_vs_evm(get_contract):
    code = """
@external
@view
def foo() -> (int128, int128, int128, int128):
    return 5%2, 5%-2, -5%2, -5%-2

@external
@view
def bar(a: int128) -> bool:
    assert -5%2 == a%2
    return True
"""

    c = get_contract(code)
    assert c.foo() == [1, 1, -1, -1]
    assert c.bar(-5) is True


BAD_CODE = [
    """
@external
def foo() -> uint256:
    return 2 % 0
    """,
    """
@external
def foo() -> int128:
    return -2 % 0
    """,
    """
@external
def foo() -> decimal:
    return 2.22 % 0.0
    """,
    """
@external
def foo(a: uint256) -> uint256:
    return a % 0
    """,
    """
@external
def foo(a: int128) -> int128:
    return a % 0
    """,
    """
@external
def foo(a: decimal) -> decimal:
    return a % 0.0
    """,
]


@pytest.mark.parametrize("code", BAD_CODE)
def test_modulo_by_zero(code, assert_compile_failed, get_contract):
    assert_compile_failed(lambda: get_contract(code), ZeroDivisionException)
