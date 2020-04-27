from decimal import (
    Decimal,
)

from hypothesis import (
    example,
    given,
    settings,
    strategies as st,
)
import pytest

from vyper import (
    ast as vy_ast,
    functions as vy_fn,
)

st_decimals = st.decimals(
    min_value=-2 ** 32,
    max_value=2 ** 32,
    allow_nan=False,
    allow_infinity=False,
    places=10,
)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_decimals)
@example(value=Decimal("0.9999999999"))
@example(value=Decimal("0.0000000001"))
@example(value=Decimal("-0.9999999999"))
@example(value=Decimal("-0.0000000001"))
def test_fold_ceil(get_contract, assert_tx_failed, value):
    source = f"""
@public
def foo(a: decimal) -> int128:
    return ceil(a)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"ceil({value})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Ceil().evaluate(old_node)

    assert contract.foo(value) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_decimals)
@example(value=Decimal("0.9999999999"))
@example(value=Decimal("0.0000000001"))
@example(value=Decimal("-0.9999999999"))
@example(value=Decimal("-0.0000000001"))
def test_fold_floor(get_contract, assert_tx_failed, value):
    source = f"""
@public
def foo(a: decimal) -> int128:
    return floor(a)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"floor({value})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Floor().evaluate(old_node)

    assert contract.foo(value) == new_node.value
