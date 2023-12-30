import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn
from vyper.exceptions import InvalidType


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(a=st.integers(min_value=-(2**255) + 1, max_value=2**255 - 1))
@example(a=0)
def test_abs(get_contract, a):
    source = """
@external
def foo(a: int256) -> int256:
    return abs(a)
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"abs({a})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["abs"]._try_fold(old_node)

    assert contract.foo(a) == new_node.value == abs(a)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(a=st.integers(min_value=2**255, max_value=2**256 - 1))
def test_abs_upper_bound_folding(get_contract, a):
    source = f"""
@external
def foo(a: int256) -> int256:
    return abs({a})
    """
    with pytest.raises(InvalidType):
        get_contract(source)


def test_abs_lower_bound(get_contract, tx_failed):
    source = """
@external
def foo(a: int256) -> int256:
    return abs(a)
    """
    contract = get_contract(source)

    with tx_failed():
        contract.foo(-(2**255))


def test_abs_lower_bound_folded(get_contract, tx_failed):
    source = """
@external
def foo() -> int256:
    return abs(min_value(int256))
    """
    with pytest.raises(InvalidType):
        get_contract(source)
