import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn
from vyper.exceptions import InvalidType, OverflowException
from vyper.semantics import validate_semantics


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(a=st.integers(min_value=-(2 ** 255) + 1, max_value=2 ** 255 - 1))
@example(a=0)
def test_abs(get_contract, a):
    source = """
@external
def foo(a: int256) -> int256:
    return abs(a)
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> int256:
    return abs({a})
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.DISPATCH_TABLE["abs"].evaluate(old_node)

    assert contract.foo(a) == new_node.value == abs(a)

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == abs(a)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(a=st.integers(min_value=2 ** 255, max_value=2 ** 256 - 1))
def test_abs_upper_bound_folding(get_contract, assert_compile_failed, a):
    source = f"""
@external
def foo(a: int256) -> int256:
    return abs({a})
    """
    assert_compile_failed(lambda: get_contract(source), InvalidType)


def test_abs_lower_bound(get_contract, assert_tx_failed):
    source = """
@external
def foo(a: int256) -> int256:
    return abs(a)
    """
    contract = get_contract(source)

    assert_tx_failed(lambda: contract.foo(-(2 ** 255)))


def test_abs_lower_bound_folded(get_contract, assert_compile_failed):
    source = """
@external
def foo() -> int256:
    return abs(-2**255)
    """
    assert_compile_failed(lambda: get_contract(source), OverflowException)
