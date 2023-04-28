import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn
from vyper.utils import SizeLimits

st_decimals = st.decimals(
    min_value=SizeLimits.MIN_AST_DECIMAL,
    max_value=SizeLimits.MAX_AST_DECIMAL,
    allow_nan=False,
    allow_infinity=False,
    places=10,
)
st_int128 = st.integers(min_value=-(2**127), max_value=2**127 - 1)
st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_decimals, right=st_decimals)
@pytest.mark.parametrize("fn_name", ["min", "max"])
def test_decimal(get_contract, left, right, fn_name):
    source = f"""
@external
def foo(a: decimal, b: decimal) -> decimal:
    return {fn_name}(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{fn_name}({left}, {right})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_int128, right=st_int128)
@pytest.mark.parametrize("fn_name", ["min", "max"])
def test_int128(get_contract, left, right, fn_name):
    source = f"""
@external
def foo(a: int128, b: int128) -> int128:
    return {fn_name}(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{fn_name}({left}, {right})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_uint256, right=st_uint256)
@pytest.mark.parametrize("fn_name", ["min", "max"])
def test_min_uint256(get_contract, left, right, fn_name):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return {fn_name}(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{fn_name}({left}, {right})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert contract.foo(left, right) == new_node.value
