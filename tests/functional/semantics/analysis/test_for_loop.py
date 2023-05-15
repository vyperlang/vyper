import pytest

from vyper.ast import parse_to_ast
from vyper.exceptions import ImmutableViolation, TypeMismatch
from vyper.semantics.analysis import validate_semantics


def test_modify_iterator_function_outside_loop(namespace):
    code = """

a: uint256[3]

@internal
def foo():
    self.a[0] = 1

@internal
def bar():
    self.foo()
    for i in self.a:
        pass
    """
    vyper_module = parse_to_ast(code)
    validate_semantics(vyper_module, {})


def test_pass_memory_var_to_other_function(namespace):
    code = """

@internal
def foo(a: uint256[3]) -> uint256[3]:
    b: uint256[3] = a
    b[1] = 42
    return b


@internal
def bar():
    a: uint256[3] = [1,2,3]
    for i in a:
        self.foo(a)
    """
    vyper_module = parse_to_ast(code)
    validate_semantics(vyper_module, {})


def test_modify_iterator(namespace):
    code = """

a: uint256[3]

@internal
def bar():
    for i in self.a:
        self.a[0] = 1
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, {})


def test_modify_iterator_function_call(namespace):
    code = """

a: uint256[3]

@internal
def foo():
    self.a[0] = 1

@internal
def bar():
    for i in self.a:
        self.foo()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, {})


def test_modify_iterator_recursive_function_call(namespace):
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
    for i in self.a:
        self.bar()
    """
    vyper_module = parse_to_ast(code)
    with pytest.raises(ImmutableViolation):
        validate_semantics(vyper_module, {})


iterator_inference_codes = [
    """
@external
def main():
    for j in range(3):
        x: uint256 = j
        y: uint16 = j
    """,  # GH issue 3212
    """
@external
def foo():
    for i in [1]:
        a:uint256 = i
        b:uint16 = i
    """,  # GH issue 3374
    """
@external
def foo():
    for i in [1]:
        for j in [1]:
            a:uint256 = i
        b:uint16 = i
    """,  # GH issue 3374
    """
@external
def foo():
    for i in [1,2,3]:
        for j in [1,2,3]:
            b:uint256 = j + i
        c:uint16 = i
    """,  # GH issue 3374
]


@pytest.mark.parametrize("code", iterator_inference_codes)
def test_iterator_type_inference_checker(namespace, code):
    vyper_module = parse_to_ast(code)
    with pytest.raises(TypeMismatch):
        validate_semantics(vyper_module, {})
