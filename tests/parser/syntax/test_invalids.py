import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    TypeMismatchException,
    StructureException,
    InvalidLiteralException
)

# These functions register test cases
# for pytest functions at the end
fail_list = []


def must_fail(code, exception):
    fail_list.append((code, exception))


pass_list = []


def must_succeed(code):
    pass_list.append(code)

# TEST CASES


must_succeed("""
x: int128[3]
""")

must_succeed("""
@public
def foo(x: int128): pass
""")

must_succeed("""
@public
def foo():
    x: int128
    x = 5
""")

must_succeed("""
@public
def foo():
    x: int128  = 5
""")

must_fail("""
@public
def foo():
    x: int128 = 5
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_fail("""
@public
def foo():
    x: int128 = 5
    x = 3.5
""", TypeMismatchException)

must_succeed("""
@public
def foo():
    x: int128 = 5
    x = 3
""")

must_succeed("""
b: int128
@public
def foo():
    self.b = 7
""")

must_fail("""
b: int128
@public
def foo():
    self.b = 7.5
""", TypeMismatchException)

must_succeed("""
b: decimal
@public
def foo():
    self.b = 7.5
""")

must_succeed("""
b: decimal
@public
def foo():
    self.b = 7
""")

must_fail("""
b: int128[5]
@public
def foo():
    self.b = 7
""", TypeMismatchException)

must_succeed("""
b: int128[int128]
@public
def foo():
    x: int128 = self.b[5]
""")

must_fail("""
b: int128[int128]
@public
def foo():
    x: int128 = self.b[5.7]
""", TypeMismatchException)

must_succeed("""
b: int128[decimal]
@public
def foo():
    x: int128 = self.b[5]
""")

must_fail("""
b: int128[int128]
@public
def foo():
    self.b[3] = 5.6
""", TypeMismatchException)

must_succeed("""
b: int128[int128]
@public
def foo():
    self.b[3] = -5
""")

must_succeed("""
b: int128[int128]
@public
def foo():
    self.b[-3] = 5
""")

must_succeed("""
@public
def foo():
    x: int128[5]
    z: int128 = x[2]
""")

must_succeed("""
x: int128
@public
def foo():
    self.x = 5
""")

must_succeed("""
x: int128
@private
def foo():
    self.x = 5
""")

must_fail("""
bar: int128[3]
@public
def foo():
    self.bar = 5
""", TypeMismatchException)

must_succeed("""
bar: int128[3]
@public
def foo():
    self.bar[0] = 5
""")

must_fail("""
@public
def foo() -> address:
    return as_unitless_number([1, 2, 3])
""", TypeMismatchException)

must_succeed("""
units: {
    currency: "currency"
}
@public
def foo(x: wei_value, y: uint256(currency), z: uint256(wei*currency/sec**2)) -> uint256(sec**2):
    return x * y / z
""")

must_fail("""
@public
def baa() -> decimal:
    return 2.0**2
""", TypeMismatchException)

must_succeed("""
@public
def foo():
    throw
""")

must_succeed("""
@public
def foo():
    pass

@public
def goo():
    self.foo()
""")

must_succeed("""
@public
def foo():
    MOOSE: int128 = 45
""")

must_fail("""
@public
def foo():
    x = -self
""", TypeMismatchException)

must_fail("""
@public
def foo() -> int128:
    return
""", TypeMismatchException)

must_fail("""
@public
def foo():
    return 3
""", TypeMismatchException)

must_fail("""
@public
def foo():
    suicide(msg.sender)
    """, StructureException)

must_succeed('''
@public
def sum(a: int128, b: int128) -> int128:
    """
    Sum two signed integers.
    """
    return a + b
''')

must_fail('''
@public
def a():
    "Test"
''', InvalidLiteralException)


@pytest.mark.parametrize('bad_code,exception_type', fail_list)
def test_compilation_fails_with_exception(bad_code, exception_type):
    with raises(exception_type):
        compiler.compile(bad_code)


@pytest.mark.parametrize('good_code', pass_list)
def test_compilation_succeeds(good_code):
    assert compiler.compile(good_code) is not None
