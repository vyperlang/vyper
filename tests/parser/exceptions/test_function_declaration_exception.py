import pytest

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException

fail_list = [
    """
x: int128
@external
@const
def foo() -> int128:
    pass
    """,
    """
x: int128
@external
@monkeydoodledoo
def foo() -> int128:
    pass
    """,
    """
def foo() -> int128:
    q: int128 = 111
    return q
    """,
    """
q: int128
def foo() -> int128:
    return self.q
    """,
    """
@external
def test_func() -> int128:
    return (1, 2)
    """,
    """
@external
def __init__(a: int128 = 12):
    pass
    """,
    """
@external
def __init__() -> uint256:
    return 1
    """,
    """
@external
def __init__() -> bool:
    pass
    """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_function_declaration_exception(bad_code):
    with pytest.raises(FunctionDeclarationException):
        compiler.compile_code(bad_code)
