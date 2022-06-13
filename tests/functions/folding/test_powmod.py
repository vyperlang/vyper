import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn
from vyper.semantics import validate_semantics

st_uint256 = st.integers(min_value=0, max_value=256)
st_uint128 = st.integers(min_value=0, max_value=128)


@pytest.mark.fuzzing
@settings(max_examples=100, deadline=1000)
@given(a=st_uint256, b=st_uint256)
def test_powmod_uint256(get_contract, a, b):
    source = """
@external
def foo(a: uint256, b: uint256) -> uint256:
    return pow_mod256(a, b)
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> uint256:
    return pow_mod256({a}, {b})
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.PowMod256().evaluate(old_node)

    assert contract.foo(a, b) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(a, b)


@pytest.mark.fuzzing
@settings(max_examples=100, deadline=1000)
@given(a=st_uint128, b=st_uint128)
def test_powmod_binop_uint256(get_contract, a, b):
    source = """
@external
def foo(a: uint256, b: uint256) -> uint256:
    return pow_mod256(a, b)
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> uint256:
    return pow_mod256({a} + 1, {b} * 2)
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.PowMod256().evaluate(old_node)

    assert contract.foo(a + 1, b * 2) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(a + 1, b * 2)
