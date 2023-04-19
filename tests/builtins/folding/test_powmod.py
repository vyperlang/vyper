import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn

st_uint256 = st.integers(min_value=0, max_value=2**256)


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

    vyper_ast = vy_ast.parse_to_ast(f"pow_mod256({a}, {b})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.PowMod256().evaluate(old_node)

    assert contract.foo(a, b) == new_node.value
