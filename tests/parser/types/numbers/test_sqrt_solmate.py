from gmpy2 import isqrt
from math import isqrt as math_isqrt

import hypothesis
import pytest

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
    assert c.test() == isqrt(val)


def test_sqrt_solmate_variable(get_contract_with_gas_estimation):
    code = """
@external
def test(a: uint256) -> uint256:
    return sqrt_solmate(a)
    """

    c = get_contract_with_gas_estimation(code)

    val = 3333
    assert c.test(val) == isqrt(val)

    val = 10 ** 17
    assert c.test(val) == isqrt(val)
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
    assert c.test2() == isqrt(val)


def test_sqrt_solmate_storage(get_contract_with_gas_estimation):
    code = """
s_var: uint256

@external
def test(a: uint256) -> uint256:
    self.s_var = a + 1
    return sqrt_solmate(self.s_var)
    """

    c = get_contract_with_gas_estimation(code)
    val = 1221
    assert c.test(val) == isqrt(val + 1)
    val = 10001
    assert c.test(val) == isqrt(val + 1)


def test_sqrt_solmate_storage_internal_variable(get_contract_with_gas_estimation):

    val = 44444
    code = f"""
s_var: uint256

@external
def test2() -> uint256:
    self.s_var = {val}
    return sqrt_solmate(self.s_var)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test2() == isqrt(val)


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
        isqrt(val),
        "hello world",
    ]


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.integers(min_value=0, max_value=SizeLimits.MAX_UINT256)
)
@hypothesis.example(SizeLimits.MAX_UINT256)
@hypothesis.example(0)
@hypothesis.settings(deadline=1000)
def test_sqrt_valid_range(sqrt_solmate_contract, value):
    vyper_sqrt = sqrt_solmate_contract.test(value)
    actual_sqrt = isqrt(value)
    try:
        assert vyper_sqrt == actual_sqrt
    except AssertionError:  # warning: this needs to be handled better
        assert vyper_sqrt - actual_sqrt == 1