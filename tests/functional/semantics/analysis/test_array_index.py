import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import (
    ArrayIndexException,
    InvalidReference,
    InvalidType,
    TypeMismatch,
    UndeclaredDefinition,
)
from vyper.semantics.analysis import validate_semantics


@pytest.mark.parametrize("value", ["address", "Bytes[10]", "decimal", "bool"])
def test_type_mismatch(namespace, value):
    code = f"""

a: uint256[3]

@internal
def foo(b: {value}):
    self.a[b] = 12
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(TypeMismatch):
        validate_semantics(vyper_module, {})


@pytest.mark.parametrize("value", ["1.0", "0.0", "'foo'", "0x00", "b'\x01'", "False"])
def test_invalid_literal(namespace, value):
    code = f"""

a: uint256[3]

@internal
def foo():
    self.a[{value}] = 12
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(InvalidType):
        validate_semantics(vyper_module, {})


@pytest.mark.parametrize("value", [-1, 3, -(2**127), 2**127 - 1, 2**256 - 1])
def test_out_of_bounds(namespace, value):
    code = f"""

a: uint256[3]

@internal
def foo():
    self.a[{value}] = 12
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ArrayIndexException):
        validate_semantics(vyper_module, {})


@pytest.mark.parametrize("value", ["b", "self.b"])
def test_undeclared_definition(namespace, value):
    code = f"""

a: uint256[3]

@internal
def foo():
    self.a[{value}] = 12
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(UndeclaredDefinition):
        validate_semantics(vyper_module, {})


@pytest.mark.parametrize("value", ["a", "foo", "int128"])
def test_invalid_reference(namespace, value):
    code = f"""

a: uint256[3]

@internal
def foo():
    self.a[{value}] = 12
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(InvalidReference):
        validate_semantics(vyper_module, {})
