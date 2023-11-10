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
    a=st.integers(min_value=0, max_value=2**256 - 1),
    s=st.integers(min_value=0, max_value=31),
    le=st.integers(min_value=1, max_value=32),
)
def test_slice_bytes32(get_contract, a, s, le):
    a = hex(a)
    while len(a) < 66:
        a = f"0x0{a[2:]}"
    le = min(32, 32 - s, le)

    source = f"""
@external
def foo(a: bytes32) -> Bytes[{le}]:
    return slice(a, {s}, {le})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"slice({a}, {s}, {le})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    s *= 2
    le *= 2
    assert contract.foo(a) == new_node.value == bytes.fromhex(a[2:][s : (s + le)])


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    a=st.integers(min_value=0, max_value=2**256 - 1),
    s=st.integers(min_value=0, max_value=31),
    le=st.integers(min_value=1, max_value=32),
)
def test_slice_bytesnot32(a, s, le):
    a = hex(a)
    if len(a) == 3:
        a = f"0x0{a[2:]}"
    elif len(a) == 66:
        a = a[:-2]
    elif len(a) % 2 == 1:
        a = a[:-1]
    le = min(32, 32 - s, le)

    vyper_ast = vy_ast.parse_to_ast(f"slice({a}, {s}, {le})")
    old_node = vyper_ast.body[0].value
    with pytest.raises(ArgumentException):
        vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    a=st.binary(min_size=1, max_size=100),
    s=st.integers(min_value=0, max_value=99),
    le=st.integers(min_value=1, max_value=100),
)
def test_slice_dynbytes(get_contract, a, s, le):
    s = s % len(a)
    le = min(len(a), len(a) - s, le)

    source = f"""
@external
def foo(a: Bytes[100]) -> Bytes[{le}]:
    return slice(a, {s}, {le})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"slice({a}, {s}, {le})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    assert contract.foo(a) == new_node.value == a[s : (s + le)]


valid_char = [
    char for char in string.printable if char not in (string.whitespace.replace(" ", "") + '"\\')
]


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    a=st.text(alphabet=valid_char, min_size=1, max_size=100),
    s=st.integers(min_value=0, max_value=99),
    le=st.integers(min_value=1, max_value=100),
)
def test_slice_string(get_contract, a, s, le):
    s = s % len(a)
    le = min(len(a), len(a) - s, le)

    source = f"""
@external
def foo(a: String[100]) -> String[{le}]:
    return slice(a, {s}, {le})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f'slice("{a}", {s}, {le})')
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["slice"].evaluate(old_node)

    assert contract.foo(a) == new_node.value == a[s : (s + le)]
