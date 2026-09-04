from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import decimal_to_int, parse_and_fold

st_decimals = st.decimals(
    min_value=-(2**32), max_value=2**32, allow_nan=False, allow_infinity=False, places=10
)


def _check_floor_ceil(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: decimal) -> int256:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{fn_name}({value})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert isinstance(new_node.value, int)
    assert contract.foo(decimal_to_int(value)) == new_node.value


@pytest.mark.parametrize(
    "value",
    [
        Decimal("0.9999999999"),
        Decimal("0.0000000001"),
        Decimal("-0.9999999999"),
        Decimal("-0.0000000001"),
    ],
)
@pytest.mark.parametrize("fn_name", ["floor", "ceil"])
def test_floor_ceil(get_contract, value, fn_name):
    _check_floor_ceil(get_contract, value, fn_name)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(value=st_decimals)
@pytest.mark.parametrize("fn_name", ["floor", "ceil"])
def test_floor_ceil_fuzz(get_contract, value, fn_name):
    _check_floor_ceil(get_contract, value, fn_name)
