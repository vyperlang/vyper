import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn
from vyper.semantics import validate_semantics

denoms = [x for k in vy_fn.AsWeiValue.wei_denoms.keys() for x in k]


st_decimals = st.decimals(
    min_value=0, max_value=2 ** 32, allow_nan=False, allow_infinity=False, places=10
)


@pytest.mark.fuzzing
@settings(max_examples=10, deadline=1000)
@given(value=st_decimals)
@pytest.mark.parametrize("denom", denoms)
def test_decimal(get_contract, value, denom):
    source = f"""
@external
def foo(a: decimal) -> uint256:
    return as_wei_value(a, '{denom}')
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> uint256:
    return as_wei_value({value}, '{denom}')
    """
    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.AsWeiValue().evaluate(old_node)

    assert contract.foo(value) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)


@pytest.mark.fuzzing
@settings(max_examples=10, deadline=1000)
@given(value=st.integers(min_value=0, max_value=2 ** 128))
@pytest.mark.parametrize("denom", denoms)
def test_integer(get_contract, value, denom):
    source = f"""
@external
def foo(a: uint256) -> uint256:
    return as_wei_value(a, '{denom}')
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> uint256:
    return as_wei_value({value}, '{denom}')
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.AsWeiValue().evaluate(old_node)

    assert contract.foo(value) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)
