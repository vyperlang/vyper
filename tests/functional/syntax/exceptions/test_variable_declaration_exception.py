import pytest

from vyper import compiler
from vyper.exceptions import VariableDeclarationException

fail_list = [
    """
foo.a: int128
    """,
    """
@external
def foo():
    bar.x: int128 = 0
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_variable_declaration_exception(bad_code):
    with pytest.raises(VariableDeclarationException):
        compiler.compile_code(bad_code)


pass_list = [
    """
q: int128 = 12
@external
def foo() -> int128:
    return self.q
    """,
    """
struct S:
    x: int128
s: S = S(x=5)
    """,
]


@pytest.mark.parametrize("good_code", pass_list)
def test_variable_initialization_allowed(good_code):
    compiler.compile_code(good_code)
