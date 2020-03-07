import pytest
from pytest import (
    raises,
)

from vyper import (
    compiler,
)
from vyper.exceptions import (
    StructureException,
    TypeMismatch,
)

fail_list = [
    """
@public
def foo():
    x: int128[3] = [1, 2, 3]
    x = 4
    """,
    """
@public
def foo():
    x: int128[3] = [1, 2, 3]
    x = [4, 5, 6, 7]
    """,
    """
@public
def foo() -> int128[2]:
    return [3, 5, 7]
    """,
    """
@public
def foo() -> int128[2]:
    return [3]
    """,
    """
y: int128[3]

@public
def foo(x: int128[3]):
    self.y = x[0]
    """,
    """
y: int128[3]

@public
def foo(x: int128[3]):
    self.y[0] = x
    """,
    """
y: int128[4]

@public
def foo(x: int128[3]):
    self.y = x
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = [1, 2, 0x1234567890123456789012345678901234567890]
    """,
    ("""
bar: int128[3]
@public
def foo():
    self.bar = []
    """, StructureException),
    """
b: int128[5]
@public
def foo():
    x = self.b[0][1]
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = [1, [2], 3]
    """,
    """
bar: int128[3][3]
@public
def foo():
    self.bar = 5
    """,
    """
bar: int128[3][3]
@public
def foo():
    self.bar = [2, 5]
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = [1, 2, 3, 4]
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = [1, 2]
    """,
    """
b: int128[5]
@public
def foo():
    self.b[0] = 7.5
    """,
    """
b: int128[5]
@public
def foo():
    x = self.b[0].cow
    """,
    """
@public
def foo()->bool[2]:
    a: decimal[2] = [0.0, 0.0]
    a[0] = 1
    return a
    """,
    """
@public
def foo()->bool[2]:
    a: bool[10] = [True, True, True, True, True, True, True, True, True, True]
    a[0] = 1
    return a
    """,
    """
@public
def test() -> int128:
    a = [1, 2, 3.0]
    return a[0]
    """,
    """
@public
def test() -> int128:
    a = [1, 2, True]
    return a[0]
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


valid_list = [
    """
@public
def foo():
    x: int128[3] = [1, 2, 3]
    x = [4, 5, 6]
    """,
    """
@public
def foo() -> int128[2][2]:
    return [[1,2], [3,4]]
    """,
    """
@public
def foo() -> decimal[2][2]:
    return [[1.0, 2.0], [3.0, 4.0]]
    """,
    """
@public
def foo() -> decimal[2][2]:
    return [[1.0, 2.0], [3.5, 4.0]]
    """,
    """
@public
def foo(x: int128[3]) -> int128:
    return x[0]
    """,
    """
y: int128[3]

@public
def foo(x: int128[3]):
    self.y = x
    """,
    """
y: decimal[3]

@public
def foo(x: int128[3]):
    self.y = x
    """,
    """
y: decimal[2][2]

@public
def foo(x: int128[2][2]):
    self.y = x
    """,
    """
y: decimal[2]

@public
def foo(x: int128[2][2]):
    self.y = x[1]
    """,
    """
@public
def foo() -> int128[2]:
    return [3,5]
    """,
    """
bar: decimal[3]
@public
def foo():
    self.bar = [1.0, 2.1, 3.0]
    """,
    """
x: int128[1][2][3][4][5]
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = [1, 2, 3]
    """,
    """
b: int128[5]
@public
def foo():
    a: int128[5] = [0, 0, 0, 0, 0]
    self.b[0] = a[0]
    """,
    """
b: decimal[5]
@public
def foo():
    self.b[0] = 7
    """
]


@pytest.mark.parametrize('good_code', valid_list)
def test_list_success(good_code):
    assert compiler.compile_code(good_code) is not None
