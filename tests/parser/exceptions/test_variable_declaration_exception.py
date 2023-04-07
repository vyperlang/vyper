import pytest

from vyper import compiler
from vyper.exceptions import VariableDeclarationException

fail_list = [
    """
q: int128 = 12
@external
def foo() -> int128:
    return self.q
    """,
    """
struct S:
    x: int128
s: S = S({x: int128}, 1)
    """,
    """
struct S:
    x: int128
s: S = S()
    """,
    """
foo.a: int128
    """,
    """
@external
def foo():
    bar.x: int128 = 0
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
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_variable_declaration_exception(bad_code):
    with pytest.raises(VariableDeclarationException):
        compiler.compile_code(bad_code)
