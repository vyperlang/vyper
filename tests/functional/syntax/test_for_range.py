import pytest

from vyper import compiler
from vyper.exceptions import InvalidType, StructureException, TypeMismatch

fail_list = [
    (
        """
@external
def foo():
    for a[1] in range(10):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar():
    for i in range(1,2,bound=0):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar():
    for i in range(1,2,bound=2):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x,x+1,bound=2):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    y:uint256 = 2
    for i in range(x,y+1):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x,x+0):
        pass
    """,
        StructureException,
    ),
    (
        """
@external
def bar(x: uint256):
    for i in range(3, x):
        pass
    """,
        InvalidType,
    ),
    (
        """
FOO: constant(int128) = 3
BAR: constant(uint256) = 7
@external
def foo():
    for i in range(FOO, BAR):
        pass
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_range_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
@external
def foo():
    for i in range(10):
        pass
    """,
    """
@external
def foo():
    for i in range(10, 20):
        pass
    """,
    """
@external
def foo():
    x: int128 = 5
    for i in range(x, x + 10):
        pass
    """,
    """
interface Foo:
    def kick(): nonpayable
foos: Foo[3]
@external
def kick_foos():
    for foo in self.foos:
        foo.kick()
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_range_success(good_code):
    assert compiler.compile_code(good_code) is not None
