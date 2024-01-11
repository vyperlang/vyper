import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold
from vyper.exceptions import UnfoldableNode


# TODO expand to all signed types
@pytest.mark.fuzzing
@settings(max_examples=50)
@given(left=st.integers(), right=st.integers())
@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">=", ">"])
def test_compare_eq_signed(get_contract, op, left, right):
    source = f"""
@external
def foo(a: int128, b: int128) -> bool:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{left} {op} {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(left, right) == new_node.value


# TODO expand to all unsigned types
@pytest.mark.fuzzing
@settings(max_examples=50)
@given(left=st.integers(min_value=0), right=st.integers(min_value=0))
@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">=", ">"])
def test_compare_eq_unsigned(get_contract, op, left, right):
    source = f"""
@external
def foo(a: uint128, b: uint128) -> bool:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{left} {op} {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=20)
@given(left=st.integers(), right=st.lists(st.integers(), min_size=1, max_size=16))
def test_compare_in(left, right, get_contract):
    source = f"""
@external
def foo(a: int128, b: int128[{len(right)}]) -> bool:
    c: int128[{len(right)}] = b
    return a in c

@external
def bar(a: int128) -> bool:
    # note: codegen unrolls to `a == right[0] or a == right[1] ...`
    return a in {right}
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{left} in {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    # check runtime == fully folded
    assert contract.foo(left, right) == new_node.value
    # check unrolled runtime == fully folded
    assert contract.bar(left) == new_node.value
    # check folding matches python semantics
    assert (left in right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=20)
@given(left=st.integers(), right=st.lists(st.integers(), min_size=1, max_size=16))
def test_compare_not_in(left, right, get_contract):
    source = f"""
@external
def foo(a: int128, b: int128[{len(right)}]) -> bool:
    c: int128[{len(right)}] = b
    return a not in c

@external
def bar(a: int128) -> bool:
    # note: codegen unrolls to `a != right[0] and a != right[1] ...`
    return a not in {right}
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{left} not in {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    # check runtime == fully folded
    assert contract.foo(left, right) == new_node.value
    # check unrolled runtime == fully folded
    assert contract.bar(left) == new_node.value
    # check folding matches python semantics
    assert (left not in right) == new_node.value


@pytest.mark.parametrize("op", ["==", "!=", "<", "<=", ">=", ">"])
def test_compare_type_mismatch(op):
    vyper_ast = parse_and_fold(f"1 {op} 1.0")
    old_node = vyper_ast.body[0].value
    with pytest.raises(UnfoldableNode):
        old_node.get_folded_value()
