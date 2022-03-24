import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.exceptions import UnfoldableNode


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st.integers(), right=st.integers())
@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">=", ">"])
def test_compare_eq(get_contract, op, left, right):
    source = f"""
@external
def foo(a: int128, b: int128) -> bool:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} {op} {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.lists(st.integers(), min_size=1, max_size=16))
def test_compare_in(left, right, get_contract):
    source = f"""
@external
def foo(a: int128, b: int128[{len(right)}]) -> bool:
    c: int128[{len(right)}] = b
    return a in c
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} in {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.lists(st.integers(), min_size=1, max_size=16))
def test_compare_not_in(left, right, get_contract):
    source = f"""
@external
def foo(a: int128, b: int128[{len(right)}]) -> bool:
    c: int128[{len(right)}] = b
    return a not in c
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} not in {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">=", ">"])
def test_compare_type_mismatch(op):
    vyper_ast = vy_ast.parse_to_ast(f"1 {op} 1.0")
    old_node = vyper_ast.body[0].value
    with pytest.raises(UnfoldableNode):
        old_node.evaluate()
