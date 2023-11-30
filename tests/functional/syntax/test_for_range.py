import pytest

from vyper import compiler
from vyper.exceptions import StructureException, StateAccessViolation, ArgumentException, InvalidType, InvalidLiteral

fail_list = [
    (
        """
@external
def foo():
    for a[1] in range(10):
        pass
    """,
        StructureException("Invalid syntax for loop iterator"),
    ),
    (
        """
@external
def foo():
    x: uint256 = 100
    for _ in range(10, bound=x):
        pass
    """,
        StateAccessViolation("bound must be a literal"),
    ),
    (
        """
@external
def foo():
    for _ in range(10, 20, bound=0):
        pass
    """,
        StructureException("bound must be at least 1"),
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x,x+1,bound=2,extra=3):
        pass
    """,
        ArgumentException("Invalid keyword argument 'extra'"),
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x):
        pass
    """,
        StateAccessViolation("Value must be a literal"),
    ),
    (
        """
@external
def bar():
    for i in range(0):
        pass
    """,
        StructureException("For loop must have at least 1 iteration"),
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(0, x):
        pass
    """,
        InvalidType("Value must be a literal integer"),
    ),
    (
        """
@external
def bar():
    for i in range(2, 1):
        pass
    """,
        StructureException("Second value must be > first value")
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x, x):
        pass
    """,
        StructureException("Second element must be the first element plus a literal value")
    ),

    (
        """
@external
def bar():
    x:uint256 = 1
    y:uint256 = 1
    for i in range(x, y + 1):
        pass
    """,
        StructureException("First and second variable must be the same")
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    y:uint256 = 1
    for i in range(x, x + y):
        pass
    """,
        InvalidLiteral("Literal must be an integer")
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x, x + 0):
        pass
    """,
        StructureException(f"For loop has invalid number of iterations (0), the value must be greater than zero")
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(0, x + 1):
        pass
    """,
        InvalidType("Value must be a literal integer")
    ),
]


@pytest.mark.parametrize("bad_code,expected_error", fail_list)
def test_range_fail(bad_code, expected_error):
    with pytest.raises(type(expected_error)) as exc_info:
        compiler.compile_code(bad_code)
    assert expected_error.message == exc_info.value.message


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
@external
def foo():
    x: int128 = 5
    for i in range(1, x, bound=4):
        pass
    """,
    """
@external
def foo():
    x: int128 = 5
    for i in range(x, bound=4):
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
