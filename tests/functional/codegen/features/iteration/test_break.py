from decimal import Decimal

import pytest

from vyper.exceptions import StructureException


def test_break_test(get_contract_with_gas_estimation):
    break_test = """
@external
def foo(n: decimal) -> int128:
    c: decimal = n * 1.0
    output: int128 = 0
    for i: int128 in range(400):
        c = c / 1.2589
        if c < 1.0:
            output = i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test)

    assert c.foo(Decimal("1")) == 0
    assert c.foo(Decimal("2")) == 3
    assert c.foo(Decimal("10")) == 10
    assert c.foo(Decimal("200")) == 23

    print("Passed for-loop break test")


def test_break_test_2(get_contract_with_gas_estimation):
    break_test_2 = """
@external
def foo(n: decimal) -> int128:
    c: decimal = n * 1.0
    output: int128 = 0
    for i: int128 in range(40):
        if c < 10.0:
            output = i * 10
            break
        c = c / 10.0
    for i: int128 in range(10):
        c = c / 1.2589
        if c < 1.0:
            output = output + i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test_2)
    assert c.foo(Decimal("1")) == 0
    assert c.foo(Decimal("2")) == 3
    assert c.foo(Decimal("10")) == 10
    assert c.foo(Decimal("200")) == 23
    assert c.foo(Decimal("4000000")) == 66
    print("Passed for-loop break test 2")


def test_break_test_3(get_contract_with_gas_estimation):
    break_test_3 = """
@external
def foo(n: int128) -> int128:
    c: decimal = convert(n, decimal)
    output: int128 = 0
    for i: int128 in range(40):
        if c < 10.0:
            output = i * 10
            break
        c /= 10.0
    for i: int128 in range(10):
        c /= 1.2589
        if c < 1.0:
            output = output + i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test_3)
    assert c.foo(1) == 0
    assert c.foo(2) == 3
    assert c.foo(10) == 10
    assert c.foo(200) == 23
    assert c.foo(4000000) == 66
    print("Passed aug-assignment break composite test")


fail_list = [
    (
        """
@external
def foo():
    a: uint256 = 3
    break
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    if True:
        break
    """,
        StructureException,
    ),
    (
        """
@external
def foo():
    for i: uint256 in [1, 2, 3]:
        b: uint256 = i
    if True:
        break
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(assert_compile_failed, get_contract_with_gas_estimation, bad_code, exc):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
