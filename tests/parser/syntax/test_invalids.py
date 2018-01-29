import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


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
x: num[3]
""")

must_succeed("""
@public
def foo(x: num): pass
""")

must_succeed("""
@public
def foo():
    x: num
    x = 5
""")

must_succeed("""
@public
def foo():
    x: num  = 5
""")

must_fail("""
@public
def foo():
    x: num = 5
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_fail("""
@public
def foo():
    x: num = 5
    x = 3.5
""", TypeMismatchException)

must_succeed("""
@public
def foo():
    x: num = 5
    x = 3
""")

must_succeed("""
b: num
@public
def foo():
    self.b = 7
""")

must_fail("""
b: num
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
b: num[5]
@public
def foo():
    self.b = 7
""", TypeMismatchException)

must_succeed("""
b: num[num]
@public
def foo():
    x: num = self.b[5]
""")

must_fail("""
b: num[num]
@public
def foo():
    x: num = self.b[5.7]
""", TypeMismatchException)

must_succeed("""
b: num[decimal]
@public
def foo():
    x: num = self.b[5]
""")

must_fail("""
b: num[num]
@public
def foo():
    self.b[3] = 5.6
""", TypeMismatchException)

must_succeed("""
b: num[num]
@public
def foo():
    self.b[3] = -5
""")

must_succeed("""
b: num[num]
@public
def foo():
    self.b[-3] = 5
""")

must_succeed("""
@public
def foo():
    x: num[5]
    z: num = x[2]
""")

must_succeed("""
x: num
@public
def foo():
    self.x = 5
""")

must_succeed("""
x: num
@private
def foo():
    self.x = 5
""")

must_fail("""
foo: num[3]
@public
def foo():
    self.foo = 5
""", TypeMismatchException)

must_succeed("""
foo: num[3]
@public
def foo():
    self.foo[0] = 5
""")

must_fail("""
@public
def foo() -> address:
    return as_unitless_number([1, 2, 3])
""", TypeMismatchException)

must_succeed("""
@public
def foo(x: wei_value, y: currency_value, z: num (wei*currency/sec**2)) -> num (sec**2):
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
    MOOSE: num = 45
""")

must_fail("""
@public
def foo():
    x = -self
""", TypeMismatchException)

must_fail("""
@public
def foo() -> num:
    return
""", TypeMismatchException)

must_fail("""
@public
def foo():
    return 3
""", TypeMismatchException)

# We disabled these keywords
# throws AttributeError in this case
must_fail("""
@public
def foo():
    suicide(msg.sender)
    """, AttributeError)


@pytest.mark.parametrize('bad_code,exception_type', fail_list)
def test_compilation_fails_with_exception(bad_code, exception_type):
    with raises(exception_type):
        compiler.compile(bad_code)


@pytest.mark.parametrize('good_code', pass_list)
def test_compilation_succeeds(good_code):
    assert compiler.compile(good_code) is not None
