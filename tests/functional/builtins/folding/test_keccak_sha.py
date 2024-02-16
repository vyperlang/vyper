import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold

alphabet = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&()*+,-./:;<=>?@[]^_`{|}~'  # NOQA: E501


@pytest.mark.fuzzing
@given(value=st.text(alphabet=alphabet, min_size=0, max_size=100))
@settings(max_examples=50)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_string(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: String[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{fn_name}('''{value}''')")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert f"0x{contract.foo(value).hex()}" == new_node.value


@pytest.mark.fuzzing
@given(value=st.binary(min_size=0, max_size=100))
@settings(max_examples=50)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_bytes(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: Bytes[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{fn_name}({value})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert f"0x{contract.foo(value).hex()}" == new_node.value


@pytest.mark.fuzzing
@given(value=st.binary(min_size=1, max_size=100))
@settings(max_examples=50)
@pytest.mark.parametrize("fn_name", ["keccak256", "sha256"])
def test_hex(get_contract, value, fn_name):
    source = f"""
@external
def foo(a: Bytes[100]) -> bytes32:
    return {fn_name}(a)
    """
    contract = get_contract(source)

    value = f"0x{value.hex()}"

    vyper_ast = parse_and_fold(f"{fn_name}({value})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert f"0x{contract.foo(value).hex()}" == new_node.value
