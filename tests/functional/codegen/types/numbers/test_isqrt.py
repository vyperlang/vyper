import math

import hypothesis
import pytest

from vyper.utils import SizeLimits


@pytest.fixture(scope="module")
def isqrt_contract(get_contract_module):
    code = """
@external
def test(a: uint256) -> uint256:
    return isqrt(a)
    """
    c = get_contract_module(code)
    return c


def test_isqrt_literal(get_contract_with_gas_estimation):
    val = 2
    code = f"""
@external
def test() -> uint256:
    return isqrt({val})
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test() == math.isqrt(val)


def test_isqrt_variable(get_contract_with_gas_estimation):
    code = """
@external
def test(a: uint256) -> uint256:
    return isqrt(a)
    """

    c = get_contract_with_gas_estimation(code)

    val = 3333
    assert c.test(val) == math.isqrt(val)

    val = 10**17
    assert c.test(val) == math.isqrt(val)
    assert c.test(0) == 0


def test_isqrt_internal_variable(get_contract_with_gas_estimation):
    val = 44001
    code = f"""
@external
def test2() -> uint256:
    a: uint256 = {val}
    return isqrt(a)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test2() == math.isqrt(val)


def test_isqrt_storage(get_contract_with_gas_estimation):
    code = """
s_var: uint256

@external
def test(a: uint256) -> uint256:
    self.s_var = a + 1
    return isqrt(self.s_var)
    """

    c = get_contract_with_gas_estimation(code)
    val = 1221
    assert c.test(val) == math.isqrt(val + 1)
    val = 10001
    assert c.test(val) == math.isqrt(val + 1)


def test_isqrt_storage_internal_variable(get_contract_with_gas_estimation):
    val = 44444
    code = f"""
s_var: uint256

@external
def test2() -> uint256:
    self.s_var = {val}
    return isqrt(self.s_var)
    """
    c = get_contract_with_gas_estimation(code)
    assert c.test2() == math.isqrt(val)


def test_isqrt_inline_memory_correct(get_contract_with_gas_estimation):
    code = """
@external
def test(a: uint256) -> (uint256, uint256, uint256, uint256, uint256, String[100]):
    x: uint256 = 1
    y: uint256 = 2
    z: uint256 = 3
    e: uint256 = isqrt(a)
    f: String[100] = 'hello world'
    return a, x, y, z, e, f
    """

    c = get_contract_with_gas_estimation(code)

    val = 21
    assert c.test(val) == [val, 1, 2, 3, math.isqrt(val), "hello world"]


@pytest.mark.fuzzing
@hypothesis.given(
    value=hypothesis.strategies.integers(min_value=0, max_value=SizeLimits.MAX_UINT256)
)
@hypothesis.example(SizeLimits.MAX_UINT256)
@hypothesis.example(0)
@hypothesis.example(1)
# the following examples demonstrate correct rounding mode
# for an edge case in the babylonian method - the operand is
# a perfect square - 1
@hypothesis.example(2704)
@hypothesis.example(110889)
@hypothesis.example(32239684)
def test_isqrt_valid_range(isqrt_contract, value):
    vyper_isqrt = isqrt_contract.test(value)
    actual_isqrt = math.isqrt(value)
    assert vyper_isqrt == actual_isqrt

    # check if sqrt limits are correct
    next = vyper_isqrt + 1
    assert vyper_isqrt * vyper_isqrt <= value
    assert next * next > value
