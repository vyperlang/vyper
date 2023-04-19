import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast

st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(a=st_uint256, b=st_uint256)
@pytest.mark.parametrize("op", ["&", "|", "^", "<<", ">>"])
def test_bitwise_ops(get_contract, a, b, op):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} {op} {b}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(a, b) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_uint256)
def test_bitwise_not(get_contract, value):
    source = """
@external
def foo(a: uint256) -> uint256:
    return ~a
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"~{value}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(value) == new_node.value
