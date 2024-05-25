import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    InvalidAttribute,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownAttribute,
    VariableDeclarationException,
)

fail_list = [
    (
        """
@external
def test():
    a = 1
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def test():
    a = 33.33
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def test():
    a = "test string"
    """,
        UndeclaredDefinition,
    ),
    (
        """
@external
def test():
    a: int128 = 33.33
    """,
        TypeMismatch,
    ),
    (
        """
@external
def data() -> int128:
    s: int128[5] = [1, 2, 3, 4, 5, 6]
    return 235357
    """,
        TypeMismatch,
    ),
    (
        """
struct S:
    a: int128
    b: decimal
@external
def foo() -> int128:
    s: S = S(a=1.2, b=1)
    return s.a
    """,
        TypeMismatch,
    ),
    (
        """
struct S:
    a: int128
    b: decimal
@external
def foo() -> int128:
    s: S = S(a=1)
    """,
        VariableDeclarationException,
    ),
    (
        """
struct S:
    a: int128
    b: decimal
@external
def foo() -> int128:
    s: S = S(b=1.2, a=1)
    """,
        InvalidAttribute,
    ),
    (
        """
struct S:
    a: int128
    b: decimal
@external
def foo() -> int128:
    s: S = S(a=1, b=1.2, c=1, d=33, e=55)
    return s.a
    """,
        UnknownAttribute,
    ),
    (
        """
@external
def foo() -> bool:
    a: uint256 = -1
    return True
""",
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> bool:
    a: uint256[2] = [13, -42]
    return True
""",
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> bool:
    a: int128 = 170141183460469231731687303715884105728
    return True
""",
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_as_wei_fail(bad_code):
    with raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
struct S:
    a: int128
    b: decimal
@internal
def do_stuff() -> bool:
    return True

@external
def test():
    a: bool = self.do_stuff() or self.do_stuff()
    """,
    """
@internal
def do_stuff() -> bool:
    return True

@external
def test():
    a: bool = False or self.do_stuff()
    """,
    """
@external
def test():
    a: int128 = 1
    """,
    """
@internal
def do_stuff() -> bool:
    return True

@external
def test():
    a: bool = self.do_stuff()
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_ann_assign_success(good_code):
    assert compiler.compile_code(good_code) is not None
