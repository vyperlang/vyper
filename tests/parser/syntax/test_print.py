import pytest

from vyper import compiler

valid_list = [
    """
@external
def foo(x: uint256):
    print(x)
    """,
    """
@external
def foo(x: Bytes[1]):
    print(x)
    """,
    """
struct Foo:
    x: Bytes[128]
@external
def foo(foo: Foo):
    print(foo)
    """,
    """
struct Foo:
    x: uint256
@external
def foo(foo: Foo):
    print(foo)
    """,
    """
BAR: constant(DynArray[uint256, 5]) = [1, 2, 3, 4, 5]

@external
def foo():
    print(BAR)
    """,
    """
FOO: constant(uint256) = 1
BAR: constant(DynArray[uint256, 5]) = [1, 2, 3, 4, 5]

@external
def foo():
    print(FOO, BAR)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_print_syntax(good_code):
    assert compiler.compile_code(good_code) is not None
