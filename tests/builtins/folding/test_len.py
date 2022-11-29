import pytest

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn


@pytest.mark.parametrize("length", [0, 1, 32, 33, 64, 65, 1024])
def test_len_string(get_contract, length):
    source = """
@external
def foo(a: String[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = "a" * length

    vyper_ast = vy_ast.parse_to_ast(f"len('{value}')")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value) == new_node.value


@pytest.mark.parametrize("length", [0, 1, 32, 33, 64, 65, 1024])
def test_len_bytes(get_contract, length):
    source = """
@external
def foo(a: Bytes[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = "a" * length

    vyper_ast = vy_ast.parse_to_ast(f"len(b'{value}')")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value.encode()) == new_node.value


@pytest.mark.parametrize("length", [1, 32, 33, 64, 65, 1024])
def test_len_hex(get_contract, length):
    source = """
@external
def foo(a: Bytes[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = f"0x{'00' * length}"

    vyper_ast = vy_ast.parse_to_ast(f"len({value})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.Len().evaluate(old_node)

    assert contract.foo(value) == new_node.value
