from decimal import Decimal

import pytest

wei_denoms = {
    "femtoether": 3,
    "kwei": 3,
    "babbage": 3,
    "picoether": 6,
    "mwei": 6,
    "lovelace": 6,
    "nanoether": 9,
    "gwei": 9,
    "shannon": 9,
    "microether": 12,
    "szabo": 12,
    "milliether": 15,
    "finney": 15,
    "ether": 18,
    "kether": 21,
    "grand": 21,
}


@pytest.mark.parametrize("denom,multiplier", wei_denoms.items())
def test_wei_uint256(get_contract, assert_tx_failed, denom, multiplier):
    code = f"""
@external
def foo(a: uint256) -> uint256:
    return as_wei_value(a, "{denom}")
    """

    c = get_contract(code)

    value = (2**256 - 1) // (10**multiplier)
    assert c.foo(value) == value * (10**multiplier)

    value = (2**256 - 1) // (10 ** (multiplier - 1))
    assert_tx_failed(lambda: c.foo(value))


@pytest.mark.parametrize("denom,multiplier", wei_denoms.items())
def test_wei_int128(get_contract, assert_tx_failed, denom, multiplier):
    code = f"""
@external
def foo(a: int128) -> uint256:
    return as_wei_value(a, "{denom}")
    """

    c = get_contract(code)
    value = (2**127 - 1) // (10**multiplier)

    assert c.foo(value) == value * (10**multiplier)


@pytest.mark.parametrize("denom,multiplier", wei_denoms.items())
def test_wei_decimal(get_contract, assert_tx_failed, denom, multiplier):
    code = f"""
@external
def foo(a: decimal) -> uint256:
    return as_wei_value(a, "{denom}")
    """

    c = get_contract(code)
    value = Decimal((2**127 - 1) / (10**multiplier))

    assert c.foo(value) == value * (10**multiplier)


@pytest.mark.parametrize("value", (-1, -(2**127)))
@pytest.mark.parametrize("data_type", ["decimal", "int128"])
def test_negative_value_reverts(get_contract, assert_tx_failed, value, data_type):
    code = f"""
@external
def foo(a: {data_type}) -> uint256:
    return as_wei_value(a, "ether")
    """

    c = get_contract(code)
    assert_tx_failed(lambda: c.foo(value))


@pytest.mark.parametrize("denom,multiplier", wei_denoms.items())
@pytest.mark.parametrize("data_type", ["decimal", "int128", "uint256"])
def test_zero_value(get_contract, assert_tx_failed, denom, multiplier, data_type):
    code = f"""
@external
def foo(a: {data_type}) -> uint256:
    return as_wei_value(a, "{denom}")
    """

    c = get_contract(code)
    assert c.foo(0) == 0
