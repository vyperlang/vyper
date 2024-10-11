import pytest

from vyper.compiler import compile_code
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
def test_instantiation_exception(bad_code):
    with pytest.raises(InstantiationException):
        compile_code(bad_code)


def test_instantiation_exception_module(make_input_bundle):
    main = """
# main.vy
import lib

initializes: lib

x:lib

@external
def foo() -> (uint256, uint256):
    return (self.x.bar(), self.x.bar())
    """
    lib = """
# lib.vy
a:uint256

@internal
def bar()->uint256:
    self.a += 1
    return self.a
    """
    input_bundle = make_input_bundle({"lib.vy": lib})
    with pytest.raises(InstantiationException):
        compile_code(main, input_bundle=input_bundle)
