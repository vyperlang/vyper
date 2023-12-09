import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn
from vyper.exceptions import ArgumentException


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    bytes_in=st.binary(max_size=32),
    start=st.integers(min_value=0, max_value=31),
    length=st.integers(min_value=1, max_value=32),
)
def test_slice_bytes32(get_contract, bytes_in, start, length):
    as_hex = "0x" + str.join("", ["00" for _ in range(32 - len(bytes_in))]) + bytes_in.hex()
    length = min(32 - start, length)

    source = f"""
@external
def foo(bytes_in: bytes32) -> Bytes[{length}]:
    return slice(bytes_in, {start}, {length})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"slice({as_hex}, {start}, {length})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    start *= 2
    length *= 2
    assert contract.foo(as_hex) == new_node.value == bytes.fromhex(as_hex[2:][start : (start + length)])


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    bytes_in=st.binary(max_size=31),
    start=st.integers(min_value=0, max_value=31),
    length=st.integers(min_value=1, max_value=32),
)
def test_slice_bytesnot32(bytes_in, start, length):
    if not len(bytes_in):
        as_hex = "0x00"
    else:
        as_hex = "0x" + bytes_in.hex()
    length = min(32, 32 - start, length)

    vyper_ast = vy_ast.parse_to_ast(f"slice({as_hex}, {start}, {length})")
    old_node = vyper_ast.body[0].value
    with pytest.raises(ArgumentException):
        vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    bytes_in=st.binary(min_size=1, max_size=100),
    start=st.integers(min_value=0, max_value=99),
    length=st.integers(min_value=1, max_value=100),
)
def test_slice_dynbytes(get_contract, bytes_in, start, length):
    start = start % len(bytes_in)
    length = min(len(bytes_in), len(bytes_in) - start, length)

    source = f"""
@external
def foo(bytes_in: Bytes[100]) -> Bytes[{length}]:
    return slice(bytes_in, {start}, {length})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"slice({bytes_in}, {start}, {length})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    assert contract.foo(bytes_in) == new_node.value == bytes_in[start : (start + length)]


valid_char = [
    char for char in string.printable if char not in (string.whitespace.replace(" ", "") + '"\\')
]


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    string_in=st.text(alphabet=valid_char, min_size=1, max_size=100),
    start=st.integers(min_value=0, max_value=99),
    length=st.integers(min_value=1, max_value=100),
)
def test_slice_string(get_contract, string_in, start, length):
    start = start % len(string_in)
    length = min(len(string_in), len(string_in) - start, length)

    source = f"""
@external
def foo(string_in: String[100]) -> String[{length}]:
    return slice(string_in, {start}, {length})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f'slice("{string_in}", {start}, {length})')
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    assert contract.foo(string_in) == new_node.value == string_in[start : (start + length)]
