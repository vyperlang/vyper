import pytest

from vyper import compiler
from vyper.exceptions import (
    FunctionDeclarationException,
    InvalidOperation,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
    UnknownAttribute,
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


must_succeed(
    """
x: int128[3]
"""
)

must_succeed(
    """
@external
def foo(x: int128): pass
"""
)

must_succeed(
    """
@external
def foo():
    x: int128 = 0
    x = 5
"""
)

must_succeed(
    """
@external
def foo():
    x: int128  = 5
"""
)

must_fail(
    """
@external
def foo():
    x: int128 = 5
    x = 0x1234567890123456789012345678901234567890
""",
    TypeMismatch,
)

must_fail(
    """
@external
def foo():
    x: int128 = 5
    x = 3.5
""",
    TypeMismatch,
)

must_succeed(
    """
@external
def foo():
    x: int128 = 5
    x = 3
"""
)

must_succeed(
    """
b: int128
@external
def foo():
    self.b = 7
"""
)

must_fail(
    """
b: int128
@external
def foo():
    self.b = 7.5
""",
    TypeMismatch,
)

must_succeed(
    """
b: decimal
@external
def foo():
    self.b = 7.5
"""
)

must_succeed(
    """
b: decimal
@external
def foo():
    self.b = 7.0
"""
)

must_fail(
    """
b: int128[5]
@external
def foo():
    self.b = 7
""",
    TypeMismatch,
)

must_succeed(
    """
b: HashMap[int128, int128]
@external
def foo():
    x: int128 = self.b[5]
"""
)

must_fail(
    """
b: HashMap[uint256, uint256]
@external
def foo():
    x: int128 = self.b[-5]
""",
    TypeMismatch,
)

must_fail(
    """
b: HashMap[int128, int128]
@external
def foo():
    x: int128 = self.b[5.7]
""",
    TypeMismatch,
)

must_succeed(
    """
b: HashMap[decimal, int128]
@external
def foo():
    x: int128 = self.b[5.0]
"""
)

must_fail(
    """
b: HashMap[int128, int128]
@external
def foo():
    self.b[3] = 5.6
""",
    TypeMismatch,
)

must_succeed(
    """
b: HashMap[int128, int128]
@external
def foo():
    self.b[3] = -5
"""
)

must_succeed(
    """
b: HashMap[int128, int128]
@external
def foo():
    self.b[-3] = 5
"""
)

must_succeed(
    """
@external
def foo():
    x: int128[5] = [0, 0, 0, 0, 0]
    z: int128 = x[2]
"""
)

must_succeed(
    """
x: int128
@external
def foo():
    self.x = 5
"""
)

must_succeed(
    """
x: int128
@internal
def foo():
    self.x = 5
"""
)

must_fail(
    """
bar: int128[3]
@external
def foo():
    self.bar = 5
""",
    TypeMismatch,
)

must_succeed(
    """
bar: int128[3]
@external
def foo():
    self.bar[0] = 5
"""
)

must_fail(
    """
@external
def foo() -> address:
    return [1, 2, 3]
""",
    TypeMismatch,
)

must_fail(
    """
@external
def baa() -> decimal:
    return 2.0**2
""",
    TypeMismatch,
)

must_succeed(
    """
@external
def foo():
    raise "fail"
"""
)

must_succeed(
    """
@internal
def foo():
    pass

@external
def goo():
    self.foo()
"""
)

must_succeed(
    """
@external
def foo():
    MOOSE: int128 = 45
"""
)

must_fail(
    """
@external
def foo():
    x: address = -self
""",
    InvalidOperation,
)

must_fail(
    """
@external
def foo() -> int128:
    return
""",
    FunctionDeclarationException,
)

must_fail(
    """
@external
def foo():
    return 3
""",
    FunctionDeclarationException,
)

must_fail(
    """
@external
def foo():
    suicide(msg.sender)
    """,
    UndeclaredDefinition,
)

must_succeed(
    '''
@external
def sum(a: int128, b: int128) -> int128:
    """
    Sum two signed integers.
    """
    return a + b
'''
)

must_fail(
    """
@external
def a():
    "Behold me mortal, for I am a DOCSTRING!"
    "Alas, I am but a mere string."
""",
    StructureException,
)

must_fail(
    """
struct StructX:
    x: int128

@external
def a():
    x: int128 = StructX(y=1)
""",
    UnknownAttribute,
)

must_fail(
    """
a: HashMap
""",
    StructureException,
)


@pytest.mark.parametrize("bad_code,exception_type", fail_list)
def test_compilation_fails_with_exception(bad_code, exception_type):
    with pytest.raises(exception_type):
        compiler.compile_code(bad_code)


@pytest.mark.parametrize("good_code", pass_list)
def test_compilation_succeeds(good_code):
    assert compiler.compile_code(good_code) is not None
