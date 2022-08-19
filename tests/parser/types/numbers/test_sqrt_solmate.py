from math import sqrt

import hypothesis
import pytest
from eth_tester.exceptions import TransactionFailed

from vyper.utils import SizeLimits


@pytest.fixture(scope="module")
def sqrt_solmate_contract(get_contract_module):
    code = """
@external
def test(a: uint256) -> uint256:
    return sqrt_solmate(a)
    """
    c = get_contract_module(code)
    return c


def test_sqrt_solmate_literal(get_contract_with_gas_estimation):
    val = 2
    code = f"""
@external
def test() -> uint256:
    return sqrt_solmate({val})
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test() == sqrt(val)


def test_sqrt_solmate_variable(get_contract_with_gas_estimation):
    code = """
@external
def test(a: uint256) -> uint256:
    return sqrt_solmate(a)
    """

    c = get_contract_with_gas_estimation(code)

    val = 3333
    assert c.test(val) == sqrt(val)

    val = 1e17
    assert c.test(val) == sqrt(val)
    assert c.test(0) == 0


def test_sqrt_solmate_internal_variable(get_contract_with_gas_estimation):
    val = 44001
    code = f"""
@external
def test2() -> uint256:
    a: uint256 = {val}
    return sqrt_solmate(a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test2() == sqrt(val)


def test_sqrt_solmate_storage(get_contract_with_gas_estimation):
    code = """
s_var: uint256

@external
def test(a: uint256) -> decimal:
    self.s_var = a + 1.0
    return sqrt_solmate(self.s_var)
    """

    c = get_contract_with_gas_estimation(code)
    val = 1221
    assert c.test(val) == sqrt(val + 1)
    val = 10001
    assert c.test(val) == sqrt(val + 1)


def test_sqrt_solmate_storage_internal_variable(get_contract_with_gas_estimation):

    val = 44444
    code = f"""
s_var: uint256

@external
def test2() -> decimal:
    self.s_var = {val}
    return sqrt_solmate(self.s_var)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test2() == sqrt(val)


def test_sqrt_solmate_inline_memory_correct(get_contract_with_gas_estimation):
    code = """
@external
def test(a: uint256) -> (uint256, uint256, uint256, uint256, uint256, String[100]):
    x: uint256 = 1
    y: uint256 = 2
    z: uint256 = 3
    e: uint256 = sqrt_solmate(a)
    f: String[100] = 'hello world'
    return a, x, y, z, e, f
    """

    c = get_contract_with_gas_estimation(code)

    val = 21
    assert c.test(val) == [
        val,
        1,
        2,
        3,
        sqrt(val),
        "hello world",
    ]


@pytest.mark.parametrize("value", [0, SizeLimits.MAX_UINT256])
def test_sqrt_solmate_bounds(sqrt_solmate_contract, value):
    vyper_sqrt = sqrt_solmate_contract.test(value)
    actual_sqrt = sqrt(value)
    assert vyper_sqrt == actual_sqrt


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.integers(min_value=0, max_value=SizeLimits.MAX_UINT256)
)
@hypothesis.example(SizeLimits.MAX_UINT256)
@hypothesis.example(0)
@hypothesis.settings(deadline=1000)
def test_sqrt_valid_range(sqrt_solmate_contract, value):
    vyper_sqrt = sqrt_solmate_contract.test(value)
    actual_sqrt = sqrt(value)
    assert vyper_sqrt == actual_sqrt


def test_sqrt_invalid_range(sqrt_solmate_contract):
    val = -1
    with pytest.raises(TransactionFailed):
        sqrt_solmate_contract.test(val)
