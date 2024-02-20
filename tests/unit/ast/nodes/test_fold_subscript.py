import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold


@pytest.mark.fuzzing
@settings(max_examples=50)
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

    vyper_ast = parse_and_fold(f"{array}[{idx}]")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(array, idx) == new_node.value
