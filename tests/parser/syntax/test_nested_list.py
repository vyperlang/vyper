import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    InvalidType,
    StructureException,
    TypeMismatch,
)

fail_list = [
    ("""
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
    """, InvalidType),
    ("""
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7.0, 8.0, 9.0]]
    """, InvalidType),
    ("""
@public
def foo() -> int128[2]:
    return [[1,2],[3,4]]
    """, TypeMismatch),
    ("""
@public
def foo() -> int128[2][2]:
    return [1,2]
    """, TypeMismatch),
    ("""
y: address[2][2]

@public
def foo(x: int128[2][2]) -> int128:
    self.y = x
    return 768
    """, TypeMismatch),
    ("""
# for loops only allowed on base types
bar: int128[3][3]

@public
def foo() -> int128[3]:
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    for x in self.bar:
        if x == [4, 5, 6]:
            return x
    return [-1, -2, -3]
    """, StructureException)
]


@pytest.mark.parametrize('bad_code,exc', fail_list)
def test_nested_list_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
bar: int128[3][3]
@public
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    """,
    """
bar: decimal[3][3]
@public
def foo():
    self.bar = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_nested_list_sucess(good_code):
    assert compiler.compile_code(good_code) is not None
