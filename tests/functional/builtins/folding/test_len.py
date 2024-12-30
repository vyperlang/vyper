import pytest

from tests.utils import parse_and_fold


@pytest.mark.parametrize("length", [0, 1, 32, 33, 64, 65, 1024])
def test_len_string(get_contract, length):
    source = """
@external
def foo(a: String[1024]) -> uint256:
    return len(a)
    """
    contract = get_contract(source)

    value = "a" * length

    vyper_ast = parse_and_fold(f"len('{value}')")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

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

    vyper_ast = parse_and_fold(f"len(b'{value}')")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

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

    vyper_ast = parse_and_fold(f"len({value})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(value) == new_node.value
