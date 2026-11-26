import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    ImmutableViolation,
    StateAccessViolation,
    StructureException,
    TypeMismatch,
)

fail_list = [
    (
        """
@external
def test():
    a: int128 = 0
    b: int128 = 0
    c: int128 = 0
    a, b, c = 1, 2, 3
    """,
        StructureException,
    ),
    """
@internal
def out_literals() -> (int128, int128, Bytes[10]):
    return 1, 2, b"3333"

@external
def test() -> (int128, address, Bytes[10]):
    a: int128 = 0
    b: int128 = 0
    a, b, b = self.out_literals()  # incorrect bytes type
    return a, b, c
    """,
    """
@internal
def out_literals() -> (int128, int128, Bytes[10]):
    return 1, 2, b"3333"

@external
def test() -> (int128, address, Bytes[10]):
    a: int128 = 0
    b: address = empty(address)
    a, b = self.out_literals()  # tuple count mismatch
    return
    """,
    """
@internal
def out_literals() -> (int128, int128, int128):
    return 1, 2, 3

@external
def test() -> (int128, int128, Bytes[10]):
    a: int128 = 0
    b: int128 = 0
    c: Bytes[10] = b""
    a, b, c = self.out_literals()
    return a, b, c
    """,
    """
@internal
def out_literals() -> (int128, int128, Bytes[100]):
    return 1, 2, b"test"

@external
def test():
    a: int128 = 0
    b: int128 = 0
    c: Bytes[1] = b""
    a, b, c = self.out_literals()
    """,
    (
        """
@internal
def _test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1000
    return a, b, -1200

@external
def test(a: bytes32) -> (bytes32, uint256, int128):
    b: uint256 = 1
    c: int128 = 1
    d: int128 = 123
    a, b, c = self._test(a)
    assert d == 123
    return a, b, c
    """,
        ImmutableViolation,
    ),
    (
        """
B: immutable(uint256)

@deploy
def __init__(b: uint256):
    self.B = b

@internal
def foo() -> (uint256, uint256):
    return (1, 2)

@external
def bar():
    a: uint256 = 1
    a, self.B = self.foo()
    """,
        ImmutableViolation,
    ),
    (
        """
x: public(uint256)

@internal
@view
def return_two() -> (uint256, uint256):
    return 1, 2

@external
@view
def foo():
    a: uint256 = 0
    a, self.x = self.return_two()
     """,
        StateAccessViolation,
    ),
    (
        """
@external
def f(data: Bytes[96]) -> uint256:
    a: uint256 = 0
    b: uint256 = 0
    c: uint256 = 0
    a, (b, c) = abi_decode(data, (uint256, (uint256, uint256)))
    return a + b + c
    """,
        StructureException,
    ),
    (
        """
@internal
def g() -> (uint256, (uint256, uint256)):
    return 1, (2, 3)

@external
def f() -> uint256:
    a: uint256 = 0
    b: uint256 = 0
    c: uint256 = 0
    a, (b, c) = self.g()
    return a + b + c
    """,
        StructureException,
    ),
    (
        """
@internal
def g() -> ((uint256, uint256), uint256):
    return (1, 2), 3

@external
def f() -> uint256:
    a: uint256 = 0
    b: uint256 = 0
    c: uint256 = 0
    (a, b), c = self.g()
    return a + b + c
    """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_tuple_assign_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatch):
            compiler.compile_code(bad_code)


def test_nested_tuple_assign_target_message():
    code = """
@internal
def g() -> (uint256, (uint256, uint256)):
    return 1, (2, 3)

@external
def f():
    a: uint256 = 0
    b: uint256 = 0
    c: uint256 = 0
    a, (b, c) = self.g()
    """
    with raises(StructureException) as e:
        compiler.compile_code(code)
    assert e.value.message == "Nested tuple assignment targets are not supported"
    assert e.value.annotations[0].node_source_code == "(b, c)"
    assert e.value.hint == "assign to a tuple-typed variable and unpack it separately"


valid_list = [
    """
@internal
def g() -> (uint256, (uint256, uint256)):
    return 1, (2, 3)

@external
def f() -> uint256:
    a: uint256 = 0
    p: (uint256, uint256) = (0, 0)
    a, p = self.g()
    return a + p[0] + p[1]
    """,
    """
@internal
def g() -> (uint256, uint256):
    return 1, 2

@external
def f() -> uint256:
    a: uint256 = 0
    b: uint256 = 0
    (a, b) = self.g()
    return a + b
    """,
    """
x: uint256[2]

@internal
def g() -> (uint256, uint256):
    return 1, 2

@external
def f() -> uint256:
    a: uint256 = 0
    a, self.x[1] = self.g()
    return a + self.x[1]
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_tuple_assign_pass(good_code):
    assert compiler.compile_code(good_code) is not None
