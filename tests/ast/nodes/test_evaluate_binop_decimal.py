from hypothesis import (
    given,
    settings,
    strategies as st,
)
import pytest

from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    TypeMismatch,
)


@settings(max_examples=20, deadline=500)
@given(
    left=st.decimals(allow_nan=False, allow_infinity=False, places=10),
    right=st.decimals(allow_nan=False, allow_infinity=False, places=10),
)
def test_binop_add(left, right, get_contract):
    source = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a + b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} + {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.decimals(allow_nan=False, allow_infinity=False, places=10),
    right=st.decimals(allow_nan=False, allow_infinity=False, places=10),
)
def test_binop_sub(left, right, get_contract):
    source = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a - b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} - {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.decimals(allow_nan=False, allow_infinity=False, places=10),
    right=st.decimals(allow_nan=False, allow_infinity=False, places=10),
)
def test_binop_mul(left, right, get_contract):
    source = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a * b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} * {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.decimals(allow_nan=False, allow_infinity=False, places=10),
    right=st.decimals(allow_nan=False, allow_infinity=False, places=10).filter(lambda x: x != 0),
)
def test_binop_sdiv(left, right, get_contract):
    source = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a / b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} / {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.decimals(allow_nan=False, allow_infinity=False, places=10),
    right=st.decimals(allow_nan=False, allow_infinity=False, places=10).filter(lambda x: x != 0),
)
def test_binop_smod(left, right, get_contract):
    source = """
@public
def foo(a: decimal, b: decimal) -> decimal:
    return a % b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} % {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


def test_binop_pow():
    vyper_ast = vy_ast.parse_to_ast(f"3.1337 ** 4.2")
    old_node = vyper_ast.body[0].value

    with pytest.raises(TypeMismatch):
        old_node.evaluate()
