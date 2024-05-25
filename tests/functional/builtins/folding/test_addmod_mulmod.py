import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold

st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50)
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

    vyper_ast = parse_and_fold(f"{fn_name}({a}, {b}, {c})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(a, b, c) == new_node.value
