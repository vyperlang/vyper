import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    TypeMismatchException,
)

fail_list = [
    """
@public
def foo():
    x: bool = True
    x = 5
    """,
    ("""
@public
def foo():
    True = 3
    """, SyntaxError),
    """
@public
def foo():
    x: bool = True
    x = 129
    """,
    """
@public
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
    """,
    """
@public
def foo() -> bool:
    return (1 == 2) or 3
    """,
    """
@public
def foo() -> bool:
    return 1.0 == 1
    """,
    """
@public
def foo() -> bool:
    a: address
    return a == 1
    """,
    """
@public
def foo(a: address) -> bool:
    return not a
    """,
    """
@public
def foo() -> bool:
    b: int128
    return not b
    """,
    """
@public
def foo() -> bool:
    b: uint256
    return not b
    """,
    """
@public
def foo() -> bool:
    b: uint256
    return not b
    """,
    """
@public
def test(a: address) -> bool:
    assert(a)
    return True
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_bool_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@public
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@public
def foo():
    x: bool = True
    x = False
    """,
    """
@public
def foo() -> bool:
    return 1 == 1
    """,
    """
@public
def foo() -> bool:
    return 1 != 1
    """,
    """
@public
def foo() -> bool:
    return 1 > 1
    """,
    """
@public
def foo() -> bool:
    return 2 >= 1
    """,
    """
@public
def foo() -> bool:
    return 1 < 1
    """,
    """
@public
def foo() -> bool:
    return 1 <= 1
    """,
    """
@public
def foo2(a: address) -> bool:
    return a != ZERO_ADDRESS
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_bool_success(good_code):
    assert compiler.compile_code(good_code) is not None
