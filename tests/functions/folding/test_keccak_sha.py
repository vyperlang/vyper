import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn
from vyper.semantics import validate_semantics

alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&()*+,-./:;<=>?@[]^_`{|}~'  # NOQA: E501


@pytest.mark.fuzzing
@given(value=st.text(alphabet=alphabet, min_size=0, max_size=100))
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_string(get_contract, value, fn_name):

    source = f"""
@external
def foo(a: String[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> bytes32:
    return {fn_name}('''{value}''')
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert f"0x{contract.foo(value).hex()}" == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)


@pytest.mark.fuzzing
@given(value=st.binary(min_size=0, max_size=100))
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_bytes(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: Bytes[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    expected = f"""
@external
def foo() -> bytes32:
    return {fn_name}({value})
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert f"0x{contract.foo(value).hex()}" == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)


@pytest.mark.fuzzing
@given(value=st.binary(min_size=1, max_size=100))
@settings(max_examples=50, deadline=1000)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_hex(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: Bytes[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    value = bytes(value)

    expected = f"""
@external
def foo() -> bytes32:
    return {fn_name}({value})
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.DISPATCH_TABLE[fn_name].evaluate(old_node)

    assert f"0x{contract.foo(value).hex()}" == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)
