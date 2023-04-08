import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn

st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(a=st_uint256, b=st_uint256, c=st_uint256)
@pytest.mark.parametrize("fn_name", ["uint256_addmod", "uint256_mulmod"])
def test_modmath(get_contract, a, b, c, fn_name):
    assume(c > 0)

    source = f"""
@external
def foo(a: uint256, b: uint256, c: uint256) -> uint256:
    return {fn_name}(a, b, c)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{fn_name}({a}, {b}, {c})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert contract.foo(a, b, c) == new_node.value
