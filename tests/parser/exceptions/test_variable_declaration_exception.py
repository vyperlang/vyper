import pytest

from vyper import compiler
from vyper.exceptions import VariableDeclarationException

fail_list = [
    """
CALLDATACOPY: int128
    """,
    """
int128: bytes[3]
    """,
    """
@public
def foo():
    BALANCE: int128 = 45
    """,
    """
@public
def foo():
    true: int128 = 3
    """,
    """
q: int128 = 12
@public
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
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_variable_declaration_exception(bad_code):
    with pytest.raises(VariableDeclarationException):
        compiler.compile_code(bad_code)
