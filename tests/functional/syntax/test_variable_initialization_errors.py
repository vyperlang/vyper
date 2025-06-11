import pytest

from vyper import compile_code
from vyper.exceptions import (
    CallViolation,
    ImmutableViolation,
    StateAccessViolation,
    TypeMismatch,
    UndeclaredDefinition,
    VariableDeclarationException,
)


@pytest.mark.parametrize(
    "bad_code,exc",
    [
        (
            """
# Cannot use function calls in initializer
@external
@view
def some_func() -> uint256:
    return 42

x: uint256 = self.some_func()
    """,
            CallViolation,
        ),
        (
            """
# Cannot use self attributes in initializer
y: uint256 = 10
x: uint256 = self.y
    """,
            StateAccessViolation,
        ),
        (
            """
# Cannot use mutable expressions
x: address = msg.sender
    """,
            StateAccessViolation,
        ),
        (
            """
# Cannot use block properties
x: uint256 = block.timestamp
    """,
            StateAccessViolation,
        ),
        (
            """
# Cannot use tx properties
x: address = tx.origin
    """,
            StateAccessViolation,
        ),
        (
            """
# Cannot use msg properties
x: uint256 = msg.value
    """,
            StateAccessViolation,
        ),
        (
            """
# Cannot use complex expressions that aren't constant-foldable
x: uint256 = 2 ** block.number
    """,
            StateAccessViolation,
        ),
    ],
)
def test_invalid_initializers(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


@pytest.mark.parametrize(
    "bad_code,exc",
    [
        (
            """
# Type mismatch in initialization
x: uint256 = -1  # negative number for unsigned
    """,
            TypeMismatch,
        ),
        (
            """
# Type mismatch with wrong literal type
x: address = 123
    """,
            TypeMismatch,
        ),
        (
            """
# Boolean type mismatch
x: bool = 1
    """,
            TypeMismatch,
        ),
        (
            """
# String literal not allowed for numeric type
x: uint256 = "hello"
    """,
            TypeMismatch,
        ),
    ],
)
def test_type_mismatch_in_initialization(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)


def test_constant_requires_value():
    """Constants must have an initializer"""
    bad_code = """
X: constant(uint256)  # Missing initializer
    """
    with pytest.raises(VariableDeclarationException):
        compile_code(bad_code)


def test_immutable_requires_constructor_assignment_without_initializer():
    """Immutables without initializer must be set in constructor"""
    bad_code = """
X: immutable(uint256)  # No initializer

@deploy
def __init__():
    pass  # Forgot to set X
    """
    with pytest.raises(ImmutableViolation):
        compile_code(bad_code)


def test_initializer_cannot_reference_other_storage_vars():
    """Initializers cannot reference other storage variables"""
    bad_code = """
a: uint256 = 100
b: uint256 = self.a + 50  # Cannot reference self.a
    """
    with pytest.raises(StateAccessViolation):
        compile_code(bad_code)


def test_circular_reference_in_constants():
    """Constants cannot have circular references"""
    bad_code = """
A: constant(uint256) = B
B: constant(uint256) = A
    """
    with pytest.raises(UndeclaredDefinition):
        compile_code(bad_code)
