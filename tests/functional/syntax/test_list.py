import pytest

from vyper import compiler
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    x: int128[3] = [1, 2, 3]
    x = 4
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    x: int128[3] = [1, 2, 3]
    x = [4, 5, 6, 7]
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> int128[2]:
    return [3, 5, 7]
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo() -> int128[2]:
    return [3]
    """,
        TypeMismatch,
    ),
    (
        """
y: int128[3]

@external
def foo(x: int128[3]):
    self.y = x[0]
    """,
        TypeMismatch,
    ),
    (
        """
y: int128[3]

@external
def foo(x: int128[3]):
    self.y[0] = x
    """,
        TypeMismatch,
    ),
    (
        """
y: int128[4]

@external
def foo(x: int128[3]):
    self.y = x
    """,
        TypeMismatch,
    ),
    (
        """
y: decimal[2]

@external
def foo(x: int128[2][2]):
    self.y = x[1]
    """,
        TypeMismatch,
    ),
    (
        """
bar: int128[3]
@external
def foo():
    self.bar = [1, 2, 0x1234567890123456789012345678901234567890]
    """,
        InvalidLiteral,
    ),
    (
        """
bar: int128[3]
@external
def foo():
    self.bar = []
    """,
        TypeMismatch,
    ),
    (
        """
b: int128[5]
@external
def foo():
    x: int128 = self.b[0][1]
    """,
        StructureException,
    ),
    (
        """
bar: int128[3]
@external
def foo():
    self.bar = [1, [2], 3]
    """,
        InvalidLiteral,
    ),
    (
        """
bar: int128[3][3]
@external
def foo():
    self.bar = 5
    """,
        TypeMismatch,
    ),
    (
        """
bar: int128[3][3]
@external
def foo():
    self.bar = [2, 5]
    """,
        TypeMismatch,
    ),
    (
        """
bar: int128[3]
@external
def foo():
    self.bar = [1, 2, 3, 4]
    """,
        TypeMismatch,
    ),
    (
        """
bar: int128[3]
@external
def foo():
    self.bar = [1, 2]
    """,
        TypeMismatch,
    ),
    (
        """
b: int128[5]
@external
def foo():
    self.b[0] = 7.5
    """,
        TypeMismatch,
    ),
    (
        """
b: int128[5]
@external
def foo():
    x: int128[5] = self.b[0].cow
    """,
        StructureException,
    ),
    (
        """
@external
def foo()->bool[2]:
    a: decimal[2] = [0.0, 0.0]
    a[0] = 1
    return a
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo()->bool[2]:
    a: bool[10] = [True, True, True, True, True, True, True, True, True, True]
    a[0] = 1
    return a
    """,
        TypeMismatch,
    ),
    (
        """
@external
def test() -> int128:
    a: int128[3] = [1, 2, 3.0]
    return a[0]
    """,
        InvalidLiteral,
    ),
    (
        """
@external
def test() -> int128:
    a: int128[3] = [1, 2, True]
    return a[0]
    """,
        InvalidLiteral,
    ),
    (
        """
y: decimal[3]

@external
def foo(x: int128[3]):
    self.y = x
    """,
        TypeMismatch,
    ),
    (
        """
y: decimal[2][2]

@external
def foo(x: int128[2][2]):
    self.y = x
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_block_fail(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)


valid_list = [
    """
@external
def foo():
    x: int128[3] = [1, 2, 3]
    x = [4, 5, 6]
    """,
    """
@external
def foo() -> int128[2][2]:
    return [[1,2], [3,4]]
    """,
    """
@external
def foo() -> decimal[2][2]:
    return [[1.0, 2.0], [3.0, 4.0]]
    """,
    """
@external
def foo() -> decimal[2][2]:
    return [[1.0, 2.0], [3.5, 4.0]]
    """,
    """
@external
def foo(x: int128[3]) -> int128:
    return x[0]
    """,
    """
y: int128[3]

@external
def foo(x: int128[3]):
    self.y = x
    """,
    """
@external
def foo() -> int128[2]:
    return [3,5]
    """,
    """
bar: decimal[3]
@external
def foo():
    self.bar = [1.0, 2.1, 3.0]
    """,
    """
x: int128[1][2][3][4][5]
    """,
    """
bar: int128[3]
@external
def foo():
    self.bar = [1, 2, 3]
    """,
    """
b: int128[5]
@external
def foo():
    a: int128[5] = [0, 0, 0, 0, 0]
    self.b[0] = a[0]
    """,
    """
b: decimal[5]
@external
def foo():
    self.b[0] = 7.0
    """,
    """
@external
def foo():
    x: DynArray[uint256, 3] = [1, 2, 3]
    for i: DynArray[uint256, 3] in [[], []]:
        x = i
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_list_success(good_code):
    assert compiler.compile_code(good_code) is not None
