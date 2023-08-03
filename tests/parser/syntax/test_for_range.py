import pytest

from vyper import compiler
from vyper.exceptions import ImmutableViolation, StructureException

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
interface A:
    def foo()-> uint256: nonpayable

@external
def bar(x:address):
    a: A = A(x)
    for i in range(a.foo(), bound=12):
        pass
    """,
        ImmutableViolation,
    ),
    (
        """
interface A:
    def foo()-> uint256: nonpayable

@external
def bar(x:address):
    a: A = A(x)
    for i in range(max(a.foo(), 123), bound=12):
        pass
    """,
        ImmutableViolation,
    ),
    (
        """
interface A:
    def foo()-> uint256: nonpayable

@external
def bar(x:address):
    a: A = A(x)
    for i in range(a.foo(), a.foo() + 1):
        pass
    """,
        ImmutableViolation,
    ),
    (
        """
interface A:
    def foo()-> uint256: nonpayable

@external
def bar(x:address):
    a: A = A(x)
    for i in range(min(a.foo(), 123), min(a.foo(), 123) + 1):
        pass
    """,
        ImmutableViolation,
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
    """
interface A:
    def foo()-> uint256: view

@external
def bar(x:address):
    a: A = A(x)
    for i in range(a.foo(), bound=12):
        pass
    """,
    """
interface A:
    def foo()-> uint256: view

@external
def bar(x:address):
    a: A = A(x)
    for i in range(max(a.foo(), 123), bound=12):
        pass
    """,
    """
interface A:
    def foo()-> uint256: view

@external
def bar(x:address):
    a: A = A(x)
    for i in range(a.foo(), a.foo() + 1):
        pass
    """,
    """
interface A:
    def foo()-> uint256: view

@external
def bar(x:address):
    a: A = A(x)
    for i in range(min(a.foo(), 123), min(a.foo(), 123) + 1):
        pass
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_range_success(good_code):
    assert compiler.compile_code(good_code) is not None
