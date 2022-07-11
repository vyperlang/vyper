import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn

st_uint256 = st.integers(min_value=0, max_value=256)
st_int128 = st.integers(min_value=-128, max_value=127)


@pytest.mark.fuzzing
@settings(max_examples=100, deadline=1000)
@given(a=st_uint256, b=st_int128)
def test_shift_uint256(get_contract, a, b):
    source = """
@external
def foo(a: uint256, b: int128) -> uint256:
    return shift(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"shift({a}, {b})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Shift().evaluate(old_node)

    assert contract.foo(a, b) == new_node.value
