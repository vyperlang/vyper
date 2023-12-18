import re

import pytest

from vyper import compiler
from vyper.exceptions import ArgumentException, StateAccessViolation, StructureException

fail_list = [
    (
        """
@external
def foo():
    for a[1] in range(10):
        pass
    """,
        StructureException,
        "Invalid syntax for loop iterator",
        "a[1]",
    ),
    (
        """
@external
def foo():
    x: uint256 = 100
    for _ in range(10, bound=x):
        pass
    """,
        StateAccessViolation,
        "Bound must be a literal",
        "x",
    ),
    (
        """
@external
def foo():
    for _ in range(10, 20, bound=5):
        pass
    """,
        StructureException,
        "For loop has invalid number of iterations (10), "
        "the value must be between zero and the bound",
        "range(10, 20, bound=5)",
    ),
    (
        """
@external
def foo():
    for _ in range(10, 20, bound=0):
        pass
    """,
        StructureException,
        "Bound must be at least 1",
        "0",
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x,x+1,bound=2,extra=3):
        pass
    """,
        ArgumentException,
        "Invalid keyword argument 'extra'",
        "extra=3",
    ),
    (
        """
@external
def bar():
    for i in range(0):
        pass
    """,
        StructureException,
        "End must be greater than start",
        "0",
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x):
        pass
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "x",
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(0, x):
        pass
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "x",
    ),
    (
        """
@external
def repeat(n: uint256) -> uint256:
    for i in range(0, n * 10):
        pass
    return n
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "n * 10",
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(0, x + 1):
        pass
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "x + 1",
    ),
    (
        """
@external
def bar():
    for i in range(2, 1):
        pass
    """,
        StructureException,
        "End must be greater than start",
        "1",
    ),
    (
        """
@external
def bar():
    x:uint256 = 1
    for i in range(x, x):
        pass
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "x",
    ),
    (
        """
@external
def foo():
    x: int128 = 5
    for i in range(x, x + 10):
        pass
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "x",
    ),
    (
        """
@external
def repeat(n: uint256) -> uint256:
    for i in range(n, 6):
        pass
    return x
    """,
        StateAccessViolation,
        "Value must be a literal integer, unless a bound is specified",
        "n",
    ),
]

for_code_regex = re.compile(r"for .+ in (.*):")
fail_test_names = [
    f"{i:02d}: {for_code_regex.search(code).group(1)} raises {type(err).__name__}"
    for i, (code, err, msg, src) in enumerate(fail_list)
]


@pytest.mark.parametrize("bad_code,error_type,message,source_code", fail_list, ids=fail_test_names)
def test_range_fail(bad_code, error_type, message, source_code):
    with pytest.raises(error_type) as exc_info:
        compiler.compile_code(bad_code)
    assert message == exc_info.value.message
    assert source_code == exc_info.value.args[1].node_source_code


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
@external
def foo():
    x: int128 = 5
    for i in range(0, x, bound=4):
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

valid_test_names = [
    f"{i} {for_code_regex.search(code).group(1)}" for i, code in enumerate(valid_list)
]


@pytest.mark.parametrize("good_code", valid_list, ids=valid_test_names)
def test_range_success(good_code):
    assert compiler.compile_code(good_code) is not None
