import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn

st_uint256 = st.integers(min_value=0, max_value=2 ** 256 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(a=st_uint256, b=st_uint256)
@pytest.mark.parametrize("fn_name", ["bitwise_and", "bitwise_or", "bitwise_xor"])
def test_bitwise(get_contract, a, b, fn_name):

    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return {fn_name}(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{fn_name}({a}, {b})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert contract.foo(a, b) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_uint256)
def test_bitwise_not(get_contract, value):

    source = """
@external
def foo(a: uint256) -> uint256:
    return bitwise_not(a)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"bitwise_not({value})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.BitwiseNot().evaluate(old_node)

    assert contract.foo(value) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_uint256, steps=st.integers(min_value=-256, max_value=256))
def test_shift(get_contract, value, steps):

    source = """
@external
def foo(a: uint256, b: int128) -> uint256:
    return shift(a, b)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"shift({value}, {steps})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Shift().evaluate(old_node)

    assert contract.foo(value, steps) == new_node.value
