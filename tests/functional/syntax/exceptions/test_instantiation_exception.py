import pytest

from vyper.exceptions import InstantiationException

invalid_list = [
    """
event Foo:
    a: uint256

@external
def foo() -> Foo:
    return Foo(2)
    """,
    """
event Foo:
    a: uint256

@external
def foo() -> (uint256, Foo):
    return 1, Foo(2)
    """,
    """
a: HashMap[uint256, uint256]

@external
def foo() -> HashMap[uint256, uint256]:
    return self.a
    """,
    """
event Foo:
    a: uint256

@external
def foo(x: Foo):
    pass
    """,
    """
@external
def foo(x: HashMap[uint256, uint256]):
    pass
    """,
    """
event Foo:
    a: uint256

foo: Foo
    """,
    """
event Foo:
    a: uint256

@external
def foo():
    f: Foo = Foo(1)
    pass
    """,
    """
event Foo:
    a: uint256

b: HashMap[uint256, Foo]
    """,
    """
event Foo:
    a: uint256

b: HashMap[Foo, uint256]
    """,
    """
b: immutable(HashMap[uint256, uint256])

@deploy
def __init__():
    b = empty(HashMap[uint256, uint256])
    """,
]


@pytest.mark.parametrize("bad_code", invalid_list)
def test_instantiation_exception(bad_code, get_contract, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), InstantiationException)
