import pytest

from vyper import compiler

valid_list = [
    """
x: public(int128)
    """,
    """
x: public(constant(int128)) = 0
y: public(immutable(int128))

@deploy
def __init__():
    y = 0
    """,
    """
x: public(int128)
y: public(int128)
z: public(int128)

@external
def foo() -> int128:
    return self.x // self.y // self.z
    """,
    # expansion of public user-defined struct
    """
struct Foo:
    a: uint256

x: public(HashMap[uint256, Foo])
    """,
    # expansion of public user-defined flag
    """
flag Foo:
    BAR

x: public(HashMap[uint256, Foo])
    """,
    # expansion of public user-defined interface
    """
interface Foo:
    def bar(): nonpayable

x: public(HashMap[uint256, Foo])
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_public_success(good_code):
    assert compiler.compile_code(good_code) is not None
