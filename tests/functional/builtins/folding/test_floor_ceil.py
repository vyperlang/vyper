from decimal import Decimal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold

st_decimals = st.decimals(
    min_value=-(2**32), max_value=2**32, allow_nan=False, allow_infinity=False, places=10
)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(value=st_decimals)
@example(value=Decimal("0.9999999999"))
@example(value=Decimal("0.0000000001"))
@example(value=Decimal("-0.9999999999"))
@example(value=Decimal("-0.0000000001"))
@pytest.mark.parametrize("fn_name", ["floor", "ceil"])
def test_floor_ceil(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: decimal) -> int256:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{fn_name}({value})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(value) == new_node.value
