import pytest

from vyper import ast as vy_ast
from vyper import builtin_functions as vy_fn
from vyper.semantics import validate_semantics


@pytest.mark.parametrize("length", [0, 1, 32, 33, 64, 65, 1024])
def test_len_string(get_contract, length):
    source = """
@external
def foo(a: String[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = "a" * length

    expected = f"""
@external
def foo() -> uint256:
    return len('''{value}''')
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)


@pytest.mark.parametrize("length", [0, 1, 32, 33, 64, 65, 1024])
def test_len_bytes(get_contract, length):
    source = """
@external
def foo(a: Bytes[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = "a" * length

    expected = f"""
@external
def foo() -> uint256:
    return len(b'{value}')
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value.encode()) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value.encode())


@pytest.mark.parametrize("length", [1, 32, 33, 64, 65, 1024])
def test_len_hex(get_contract, length):
    source = """
@external
def foo(a: Bytes[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = f"0x{'01' * length}"
    input_val = "\x01" * length

    expected = f"""
@external
def foo() -> uint256:
    return len(b'{input_val}')
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value) == new_node.value

    folded_contract = get_contract(expected)
    assert folded_contract.foo() == contract.foo(value)
