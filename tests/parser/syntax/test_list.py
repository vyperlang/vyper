import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException, StructureException


fail_list = [
    """
@public
def foo():
    x: num[3] = [1, 2, 3]
    x = 4
    """,
    """
@public
def foo():
    x: num[3] = [1, 2, 3]
    x = [4, 5, 6, 7]
    """,
    """
@public
def foo() -> num[2]:
    return [3, 5, 7]
    """,
    """
@public
def foo() -> num[2]:
    return [3]
    """,
    """
y: num[3]

@public
def foo(x: num[3]):
    self.y = x[0]
    """,
    """
y: num[3]

@public
def foo(x: num[3]):
    self.y[0] = x
    """,
    """
y: num[4]

@public
def foo(x: num[3]):
    self.y = x
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = [1, 2, 0x1234567890123456789012345678901234567890]
    """,
    ("""
foo: num[3]
@public
def foo():
    self.foo = []
    """, StructureException),
    """
b: num[5]
@public
def foo():
    x = self.b[0][1]
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = [1, [2], 3]
    """,
    """
bar: num[3][3]
@public
def foo():
    self.bar = 5
    """,
    """
bar: num[3][3]
@public
def foo():
    self.bar = [2, 5]
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = [1, 2, 3, 4]
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = [1, 2]
    """,
    """
b: num[5]
@public
def foo():
    self.b[0] = 7.5
    """,
    """
b: num[5]
@public
def foo():
    x = self.b[0].cow
    """,
    """
@public
def foo()->bool[2]:
    a: decimal[2]
    a[0] = 1
    return a
    """,
    """
@public
def foo()->bool[2]:
    a: bool[1000]
    a[0] = 1
    return a
    """,
    """
@public
def test() -> num:
    a = [1, 2, 3.0]
    return a[0]
    """,
    """
@public
def test() -> num:
    a = [1, 2, true]
    return a[0]
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):

    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
@public
def foo():
    x: num[3] = [1, 2, 3]
    x = [4, 5, 6]
    """,
    """
@public
def foo() -> num[2][2]:
    return [[1,2],[3,4]]
    """,
    """
@public
def foo() -> decimal[2][2]:
    return [[1,2],[3,4]]
    """,
    """
@public
def foo() -> decimal[2][2]:
    return [[1.0, 2.0], [3.5, 4.0]]
    """,
    """
@public
def foo(x: num[3]) -> num:
    return x[0]
    """,
    """
y: num[3]

@public
def foo(x: num[3]):
    self.y = x
    """,
    """
y: decimal[3]

@public
def foo(x: num[3]):
    self.y = x
    """,
    """
y: decimal[2][2]

@public
def foo(x: num[2][2]):
    self.y = x
    """,
    """
y: decimal[2]

@public
def foo(x: num[2][2]):
    self.y = x[1]
    """,
    """
@public
def foo() -> num[2]:
    return [3,5]
    """,
    """
foo: decimal[3]
@public
def foo():
    self.foo = [1.0, 2.1, 3.0]
    """,
    """
x: num[1][2][3][4][5]
    """,
    """
foo: num[3]
@public
def foo():
    self.foo = [1, 2, 3]
    """,
    """
b: num[5]
@public
def foo():
    a: num[5]
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
    assert compiler.compile(good_code) is not None
