import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    InvalidOperation,
    InvalidType,
    SyntaxException,
    TypeMismatch,
)

fail_list = [
    (
        """
@external
def foo():
    x: bool = True
    x = 5
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    True = 3
    """,
        SyntaxException,
    ),
    (
        """
@external
def foo():
    x: bool = True
    x = 129
    """,
        InvalidType,
    ),
    (
        """
@external
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
    """,
        TypeMismatch,
    ),
    """
@external
def foo() -> bool:
    return (1 == 2) or 3
    """,
    """
@external
def foo() -> bool:
    return 1.0 == 1
    """,
    """
@external
def foo() -> bool:
    a: address = ZERO_ADDRESS
    return a == 1
    """,
    (
        """
@external
def foo(a: address) -> bool:
    return not a
    """,
        InvalidOperation,
    ),
    """
@external
def foo() -> bool:
    b: int128 = 0
    return not b
    """,
    """
@external
def foo() -> bool:
    b: uint256 = 0
    return not b
    """,
    """
@external
def foo() -> bool:
    b: uint256 = 0
    return not b
    """,
    (
        """
@external
def test(a: address) -> bool:
    assert(a)
    return True
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_bool_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@external
def foo():
    x: bool = True
    z: bool = x and False
    """,
    """
@external
def foo():
    x: bool = True
    x = False
    """,
    """
@external
def foo() -> bool:
    return 1 == 1
    """,
    """
@external
def foo() -> bool:
    return 1 != 1
    """,
    """
@external
def foo() -> bool:
    return 1 > 1
    """,
    """
@external
def foo() -> bool:
    return 2 >= 1
    """,
    """
@external
def foo() -> bool:
    return 1 < 1
    """,
    """
@external
def foo() -> bool:
    return 1 <= 1
    """,
    """
@external
def foo2(a: address) -> bool:
    return a != ZERO_ADDRESS
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_bool_success(good_code):
    assert compiler.compile_code(good_code) is not None
