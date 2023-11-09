import math

import pytest

VALID_BITS = list(range(8, 257, 8))


@pytest.mark.parametrize("bits", VALID_BITS)
def test_mkstr(get_contract_with_gas_estimation, bits):
    n_digits = math.ceil(bits * math.log(2) / math.log(10))
    code = f"""
@external
def foo(inp: uint{bits}) -> String[{n_digits}]:
    return uint2str(inp)
    """

    c = get_contract_with_gas_estimation(code)
    for i in [1, 2, 2**bits - 1, 0]:
        assert c.foo(i) == str(i), (i, c.foo(i))


# test for buffer overflow
@pytest.mark.parametrize("bits", VALID_BITS)
def test_mkstr_buffer(get_contract, bits):
    n_digits = math.ceil(bits * math.log(2) / math.log(10))
    code = f"""
some_string: String[{n_digits}]
@internal
def _foo(x: uint{bits}):
    self.some_string = uint2str(x)

@external
def foo(x: uint{bits}) -> uint256:
    y: uint256 = 0
    self._foo(x)
    return y
    """
    c = get_contract(code)
    assert c.foo(2**bits - 1) == 0, bits
