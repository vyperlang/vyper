import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import NamespaceCollision, UndeclaredDefinition

fail_list = [
    """
@external
def foo(choice: bool):
    if (choice):
        a: int128 = 1
    a += 1
    """,
    """
@external
def foo(choice: bool):
    if (choice):
        a: int128 = 0
    else:
        a: int128 = 1
    a += 1
    """,
    """
@external
def foo(choice: bool):
    if (choice):
        a: int128 = 0
    else:
        a += 1
    """,
    """
@external
def foo(choice: bool):

    for i: int128 in range(4):
        a: int128 = 0
    a = 1
    """,
    """
@external
def foo(choice: bool):

    for i: int128 in range(4):
        a: int128 = 0
    a += 1
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_fail_undeclared(bad_code):
    with raises(UndeclaredDefinition):
        compiler.compile_code(bad_code)


fail_list_collision = [
    """
@external
def foo():
    a: int128 = 5
    a: int128 = 7
    """
]


@pytest.mark.parametrize("bad_code", fail_list_collision)
def test_fail_collision(bad_code):
    with raises(NamespaceCollision):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo(choice: bool, choice2: bool):
    if (choice):
        a: int128 = 11
        if choice2 and a > 1:
            a -= 1  # should be visible here.
    """,
    """
@external
def foo(choice: bool):
    if choice:
        a: int128 = 44
    else:
        a: uint256 = 42
    a: bool = True
    """,
    """
a: int128

@external
def foo():
    a: int128 = 5
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_valid_blockscope(good_code):
    assert compiler.compile_code(good_code) is not None
