import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    InvalidType,
)

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
x: bytes <= wei
    """,
    """
x: string <= 33
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
    with raises(InvalidType):
        compiler.compile_code(bad_code)
