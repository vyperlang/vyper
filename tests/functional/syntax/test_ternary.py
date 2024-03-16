import pytest

from vyper import compile_code
from vyper.exceptions import TypeMismatch

good_list = [
    # basic test
    """
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a if a > b else b
    """,
    """
@external
def foo():
    a: bool = (True if True else True) or True
    """,
    # different locations:
    """
b: uint256

@external
def foo(x: uint256) -> uint256:
    return x if x > self.b else self.b
    """,
    # different kinds of test exprs
    """
@external
def foo(x: uint256, t: bool) -> uint256:
    return x if t else 1
    """,
    """
@external
def foo(x: uint256) -> uint256:
    return x if True else 1
    """,
    """
@external
def foo(x: uint256) -> uint256:
    return x if False else 1
    """,
    # more complex types
    """
@external
def foo(t: bool) -> DynArray[uint256, 1]:
    return [2] if t else [1]
    """,
    # TODO: get this working, depends #3377
    #    """
    # @external
    # def foo(t: bool) -> DynArray[uint256, 1]:
    #    return [] if t else [1]
    #    """,
    """
@external
def foo(t: bool) -> (uint256, uint256):
    a: uint256 = 0
    b: uint256 = 1
    return (a, b) if t else (b, a)
    """,
]


@pytest.mark.parametrize("code", good_list)
def test_ternary_good(code):
    assert compile_code(code) is not None


fail_list = [
    (  # bad test type
        """
@external
def foo() -> uint256:
    return 1 if 1 else 2
    """,
        TypeMismatch,
    ),
    (  # bad test type: constant
        """
TEST: constant(uint256) = 1
@external
def foo() -> uint256:
    return 1 if TEST else 2
    """,
        TypeMismatch,
    ),
    (  # bad test type: variable
        """
TEST: constant(uint256) = 1
@external
def foo(t: uint256) -> uint256:
    return 1 if t else 2
    """,
        TypeMismatch,
    ),
    (  # mismatched body and orelse: literal
        """
@external
def foo() -> uint256:
    return 1 if True else 2.0
    """,
        TypeMismatch,
    ),
    (  # mismatched body and orelse: literal and known type
        """
T: constant(uint256) = 1
@external
def foo() -> uint256:
    return T if True else 2.0
    """,
        TypeMismatch,
    ),
    (  # mismatched body and orelse: both variable
        """
@external
def foo(x: uint256, y: uint8) -> uint256:
    return x if True else y
    """,
        TypeMismatch,
    ),
    (  # mismatched tuple types
        """
@external
def foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a, b) if True else (a, b, c)
    """,
        TypeMismatch,
    ),
    (  # mismatched tuple types - other direction
        """
@external
def foo(a: uint256, b: uint256, c: uint256) -> (uint256, uint256):
    return (a, b, c) if True else (a, b)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("code,exc", fail_list)
def test_functions_call_fail(code, exc):
    with pytest.raises(exc):
        compile_code(code)
