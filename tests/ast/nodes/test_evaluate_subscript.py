import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(
    idx=st.integers(min_value=0, max_value=9),
    array=st.lists(st.integers(), min_size=10, max_size=10),
)
def test_subscript(get_contract, array, idx):
    source = """
@external
def foo(array: int128[10], idx: uint256) -> int128:
    return array[idx]
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{array}[{idx}]")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(array, idx) == new_node.value
