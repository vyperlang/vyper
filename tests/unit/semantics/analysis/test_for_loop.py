import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import (
    ArgumentException,
    ImmutableViolation,
    StateAccessViolation,
    TypeMismatch,
)
from vyper.semantics.analysis import validate_semantics


def test_modify_iterator_function_outside_loop(dummy_input_bundle):
    code = """

a: uint256[3]

@internal
def foo():
    self.a[0] = 1

@internal
def bar():
    self.foo()
    for i: uint256 in self.a:
        pass
    """
    vyper_module = parse_to_ast(code)
    validate_semantics(vyper_module, dummy_input_bundle)


def test_pass_memory_var_to_other_function(dummy_input_bundle):
    code = """

@internal
def foo(a: uint256[3]) -> uint256[3]:
    b: uint256[3] = a
    b[1] = 42
    return b


@internal
def bar():
    a: uint256[3] = [1,2,3]
    for i: uint256 in a:
        self.foo(a)
    """
    vyper_module = parse_to_ast(code)
    validate_semantics(vyper_module, dummy_input_bundle)


def test_modify_iterator(dummy_input_bundle):
    code = """

a: uint256[3]

@internal
def bar():
    for i: uint256 in self.a:
        self.a[0] = 1
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, dummy_input_bundle)


def test_bad_keywords(dummy_input_bundle):
    code = """

@internal
def bar(n: uint256):
    x: uint256 = 0
    for i: uint256 in range(n, boundddd=10):
        x += i
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ArgumentException):
        validate_semantics(vyper_module, dummy_input_bundle)


def test_bad_bound(dummy_input_bundle):
    code = """

@internal
def bar(n: uint256):
    x: uint256 = 0
    for i: uint256 in range(n, bound=n):
        x += i
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(StateAccessViolation):
        validate_semantics(vyper_module, dummy_input_bundle)


def test_modify_iterator_function_call(dummy_input_bundle):
    code = """

a: uint256[3]

@internal
def foo():
    self.a[0] = 1

@internal
def bar():
    for i: uint256 in self.a:
        self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, dummy_input_bundle)


def test_modify_iterator_recursive_function_call(dummy_input_bundle):
    code = """

a: uint256[3]

@internal
def foo():
    self.a[0] = 1

@internal
def bar():
    self.foo()

@internal
def baz():
    for i: uint256 in self.a:
        self.bar()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, dummy_input_bundle)
