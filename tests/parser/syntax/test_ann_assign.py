import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
    TypeMismatchException,
    VariableDeclarationException,
)

fail_list = [
    """
@public
def test():
    a = 1
    """,
    """
@public
def test():
    a = 33.33
    """,
    """
@public
def test():
    a = "test string"
    """,
    ("""
@public
def test():
    a: int128 = 33.33
    """, TypeMismatchException),
    ("""
struct S:
    a: int128
    b: decimal
@private
def do_stuff() -> bool:
    return True

@public
def test():
    a: bool = self.do_stuff() or self.do_stuff()
    """, StructureException),
    ("""
@private
def do_stuff() -> bool:
    return True

@public
def test():
    a: bool = False or self.do_stuff()
    """, StructureException),
    ("""
@public
def data() -> int128:
    s: int128[5] = [1, 2, 3, 4, 5, 6]
    return 235357
    """, TypeMismatchException),
    ("""
struct S:
    a: int128
    b: decimal
@public
def foo() -> int128:
    s: S = S({a: 1.2, b: 1})
    return s.a
    """, TypeMismatchException),
    ("""
struct S:
    a: int128
    b: decimal
@public
def foo() -> int128:
    s: S = S({b: 1.2, c: 1, d: 33, e: 55})
    return s.a
    """, TypeMismatchException),
    ("""
@public
def foo() -> bool:
    a: uint256 = -1
    return True
""", InvalidLiteralException),
    ("""
@public
def foo() -> bool:
    a: uint256[2] = [13, -42]
    return True
""", InvalidLiteralException),
    ("""
@public
def foo() -> bool:
    a: int128 = 170141183460469231731687303715884105728
    return True
""", TypeMismatchException),
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_as_wei_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(VariableDeclarationException):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def test():
    a: int128 = 1
    """,
    """
@private
def do_stuff() -> bool:
    return True

@public
def test():
    a: bool = self.do_stuff()
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_ann_assign_success(good_code):
    assert compiler.compile_code(good_code) is not None
