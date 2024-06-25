import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold
from vyper.exceptions import TypeMismatch


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

    vyper_ast = parse_and_fold(f"abs({a})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

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
    with pytest.raises(TypeMismatch):
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
    with pytest.raises(TypeMismatch):
        get_contract(source)
