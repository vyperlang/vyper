import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.exceptions import InvalidType, OverflowException
from vyper.semantics.analysis.utils import validate_expected_type
from vyper.semantics.types.shortcuts import INT256_T, UINT256_T
from vyper.utils import unsigned_to_signed

st_uint256 = st.integers(min_value=0, max_value=2**256 - 1)

st_sint256 = st.integers(min_value=-(2**255), max_value=2**255 - 1)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("op", ["&", "|", "^"])
@given(a=st_uint256, b=st_uint256)
def test_bitwise_ops(get_contract, a, b, op):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a {op} b
    """

    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} {op} {b}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(a, b) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("op", ["<<", ">>"])
@given(a=st_uint256, b=st.integers(min_value=0, max_value=256))
def test_bitwise_shift_unsigned(get_contract, a, b, op):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} {op} {b}")
    old_node = vyper_ast.body[0].value

    try:
        new_node = old_node.evaluate()
        # force bounds check, no-op because validate_numeric_bounds
        # already does this, but leave in for hygiene (in case
        # more types are added).
        validate_expected_type(new_node, UINT256_T)
    # compile time behavior does not match runtime behavior.
    # compile-time will throw on OOB, runtime will wrap.
    except OverflowException:  # here: check the wrapped value matches runtime
        assert op == "<<"
        assert contract.foo(a, b) == (a << b) % (2**256)
    else:
        assert contract.foo(a, b) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("op", ["<<", ">>"])
@given(a=st_sint256, b=st.integers(min_value=0, max_value=256))
def test_bitwise_shift_signed(get_contract, a, b, op):
    source = f"""
@external
def foo(a: int256, b: uint256) -> int256:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} {op} {b}")
    old_node = vyper_ast.body[0].value

    try:
        new_node = old_node.evaluate()
        validate_expected_type(new_node, INT256_T)  # force bounds check
    # compile time behavior does not match runtime behavior.
    # compile-time will throw on OOB, runtime will wrap.
    except (InvalidType, OverflowException):
        # check the wrapped value matches runtime
        assert op == "<<"
        assert contract.foo(a, b) == unsigned_to_signed((a << b) % (2**256), 256)
    else:
        assert contract.foo(a, b) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(value=st_uint256)
def test_bitwise_not(get_contract, value):
    source = """
@external
def foo(a: uint256) -> uint256:
    return ~a
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"~{value}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(value) == new_node.value
