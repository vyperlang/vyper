import pytest
from vyper.utils import BASE_TYPES

# TODO something less janky
numeric_types = [t for t in BASE_TYPES if "int" in t or t == "decimal"]


def _as_unsigned(x, bits):
    if x < 0:
        return x + 2**bits
    return x

def _as_signed(x, bits):
    if x > (2**(bits-1)) - 1:
        return x - 2**bits
    return x

# _int_bounds(8, True) -> (-128, 127)
# _int_bounds(8, False) -> (0, 255)
def _int_bounds(bits, signed):
    if signed:
        return -(2**(bits - 1)), (2**(bits - 1)) - 1
    return 0, (2**bits) - 1

@pytest.mark.parametrize("typ", numeric_types)
@pytest.mark.parametrize("op", [)
def test_unsafe_ops(get_contract, typ, op):
    code = f"""
@external
def bar(x: {typ}, y: {typ}) -> uint256:
    return unsafe_{op}(x, y)
    """

    c = get_contract(code)
    # TODO this should go on the type metadata
    signed = t.startswith("i") or t == "decimal"
    if 
