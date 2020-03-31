import pytest

from vyper import (
    compiler,
)
from vyper.exceptions import (
    FunctionDeclarationException,
)

fail_list = [
    """
x: int128
@public
@const
def foo() -> int128:
    pass
    """,
    """
x: int128
@public
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
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_function_declaration_exception(bad_code):
    with pytest.raises(FunctionDeclarationException):
        compiler.compile_code(bad_code)
