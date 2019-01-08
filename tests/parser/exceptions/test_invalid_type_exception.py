import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import InvalidTypeException

fail_list = [
    """
x: bat
    """,
    """
x: 5
    """,
    """
x: map(int, int128)
    """,
    """
x: int128[-1]
    """,
    """
x: int128[3.5]
    """,
    """
struct X:
    int128[5]: int128[7]
    """,
    """
x: [bar, baz]
    """,
    """
x: [bar(int128), baz(baffle)]
    """,
    """
def foo(x): pass
    """,
    """
b: map((int128, decimal), int128)
    """,
    """
b: int128[int128: address]
    """,
    """
struct Foo:
    cow: int128
    dog: int128
@public
def foo() -> Foo:
    return Foo({cow: 5, dog: 7})
    """,
    """
x: wei(wei)
    """,
    """
x: int128(address)
    """,
    """
x: int128(wei and sec)
    """,
    """
x: int128(2 ** 2)
    """,
    """
x: int128(wei ** -1)
    """,
    """
x: int128(wei >> 3)
    """,
    """
x: bytes <= wei
    """,
    """
x: string <= 33
    """,
    """
x: bytes[1:3]
    """,
    """
x: bytes[33.3]
    """,
    """
struct A:
    b: B
struct B:
    a: A
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_invalid_type_exception(bad_code):
    with raises(InvalidTypeException):
        compiler.compile_code(bad_code)
