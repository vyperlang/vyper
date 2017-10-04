from viper import compiler
from viper.exceptions import StructureException, \
    TypeMismatchException

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
def foo(x: num): pass
""")

must_succeed("""
def foo():
    x: num
    x = 5
""")

must_succeed("""
def foo():
    x = 5
""")

must_fail("""
def foo():
    x = 5
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_fail("""
def foo():
    x = 5
    x = 3.5
""", TypeMismatchException)

must_succeed("""
def foo():
    x = 5
    x = 3
""")

must_succeed("""
b: num
def foo():
    self.b = 7
""")

must_fail("""
b: num
def foo():
    self.b = 7.5
""", TypeMismatchException)

must_succeed("""
b: decimal
def foo():
    self.b = 7.5
""")


must_succeed("""
b: decimal
def foo():
    self.b = 7
""")

must_fail("""
b: num[5]
def foo():
    self.b = 7
""", TypeMismatchException)

must_succeed("""
b: decimal[5]
def foo():
    self.b[0] = 7
""")

must_fail("""
b: num[5]
def foo():
    self.b[0] = 7.5
""", TypeMismatchException)

must_succeed("""
b: num[5]
def foo():
    a: num[5]
    self.b[0] = a[0]
""")

must_fail("""
b: num[5]
def foo():
    x = self.b[0][1]
""", TypeMismatchException)

must_fail("""
b: num[5]
def foo():
    x = self.b[0].cow
""", TypeMismatchException)

must_fail("""
b: {foo: num}
def foo():
    self.b = {foo: 1, foo: 2}
""", TypeMismatchException)

must_fail("""
b: {foo: num, bar: num}
def foo():
    x = self.b.cow
""", TypeMismatchException)

must_fail("""
b: {foo: num, bar: num}
def foo():
    x = self.b[0]
""", TypeMismatchException)

must_succeed("""
b: {foo: num, bar: num}
def foo():
    x = self.b.bar
""")

must_succeed("""
b: num[num]
def foo():
    x = self.b[5]
""")

must_fail("""
b: num[num]
def foo():
    x = self.b[5.7]
""", TypeMismatchException)

must_succeed("""
b: num[decimal]
def foo():
    x = self.b[5]
""")

must_fail("""
b: num[num]
def foo():
    self.b[3] = 5.6
""", TypeMismatchException)

must_succeed("""
b: num[num]
def foo():
    self.b[3] = -5
""")

must_succeed("""
b: num[num]
def foo():
    self.b[-3] = 5
""")


must_succeed("""
def foo():
    x: num[5]
    z = x[2]
""")

must_succeed("""
x: num
def foo() -> num:
    self.x = 5
""")

must_succeed("""
x: num
@internal
def foo() -> num:
    self.x = 5
""")

must_fail("""
foo: num[3]
def foo():
    self.foo = 5
""", TypeMismatchException)

must_succeed("""
foo: num[3]
def foo():
    self.foo[0] = 5
""")

must_succeed("""
foo: num[3]
def foo():
    self.foo = [1, 2, 3]
""")

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, 2, 3, 4]
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, 2]
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, [2], 3]
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = 5
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [2, 5]
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
""", TypeMismatchException)

must_succeed("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
""")

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
""", TypeMismatchException)

must_succeed("""
bar: decimal[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
""")

must_fail("""
def foo() -> address:
    return as_unitless_number([1, 2, 3])
""", TypeMismatchException)

must_succeed("""
def foo(x: wei_value, y: currency_value, z: num (wei*currency/sec**2)) -> num (sec**2):
    return x * y / z
""")

must_fail("""
def baa() -> decimal:
    return 2.0**2
""", TypeMismatchException)

must_fail("""
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=4.0, len=3)
""", TypeMismatchException)

must_succeed("""
def foo(inp: bytes <= 10) -> num:
    return len(inp)
""")

must_fail("""
def foo(inp: num) -> num:
    return len(inp)
""", TypeMismatchException)

must_succeed("""
def foo() -> bytes <= 10:
    return "badminton"
""")

must_fail("""
def foo() -> bytes <= 10:
    return "badmintonzz"
""", TypeMismatchException)

must_succeed("""
def foo() -> bytes <= 10:
    return slice("badmintonzzz", start=1, len=10)
""")

must_fail("""
def foo() -> bytes <= 10:
    x = '0x1234567890123456789012345678901234567890'
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_succeed("""
def foo():
    x = "¡très bien!"
""")

must_succeed("""
def convert1(inp: bytes32) -> num256:
    return as_num256(inp)
""")

must_succeed("""
def foo():
    throw
""")

must_succeed("""
def foo():
    pass

def goo():
    self.foo()
""")

must_fail("""
x: {cow: num, cor: num}
def foo():
    self.x.cof = 1
""", TypeMismatchException)

must_succeed("""
def foo():
    MOOSE = 45
""")

must_fail("""
def foo():
    x = -self
""", TypeMismatchException)

must_fail("""
def foo() -> num:
    return {cow: 5, dog: 7}
""", TypeMismatchException)

must_fail("""
def foo() -> num:
    return
""", TypeMismatchException)

must_fail("""
def foo():
    return 3
""", TypeMismatchException)


# Run all of our registered tests
import pytest
from pytest import raises


@pytest.mark.parametrize('bad_code,exception_type', fail_list)
def test_compilation_fails_with_exception(bad_code, exception_type):
    with raises(exception_type):
        compiler.compile(bad_code)


@pytest.mark.parametrize('good_code', pass_list)
def test_compilation_succeeds(good_code):
    assert compiler.compile(good_code) is not None
