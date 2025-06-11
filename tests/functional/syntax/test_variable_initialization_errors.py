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
# Cannot use self in initializer
x: address = self
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
    # This will raise VyperException with multiple UndeclaredDefinition errors
    from vyper.exceptions import VyperException

    with pytest.raises((UndeclaredDefinition, VyperException)):
        compile_code(bad_code)


def test_initializer_cannot_use_pure_function_calls():
    """Cannot call even pure functions in initializers"""
    bad_code = """
@internal
@pure
def helper() -> uint256:
    return 42

x: uint256 = self.helper()
    """
    with pytest.raises(StateAccessViolation):
        compile_code(bad_code)


def test_initializer_cannot_reference_other_vars():
    """Cannot reference other storage variables regardless of order"""
    bad_code = """
y: uint256 = 100
x: uint256 = self.y  # Cannot reference self.y even though it's declared first
    """
    with pytest.raises(StateAccessViolation):
        compile_code(bad_code)
