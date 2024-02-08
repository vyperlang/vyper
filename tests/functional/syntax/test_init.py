import pytest

from vyper.compiler import compile_code
from vyper.exceptions import FunctionDeclarationException

good_list = [
    """
@deploy
def __init__():
    pass
    """,
    """
@deploy
@payable
def __init__():
    pass
    """,
    """
counter: uint256
SOME_IMMUTABLE: immutable(uint256)

@deploy
def __init__():
    SOME_IMMUTABLE = 5
    self.counter = 1
    """,
]


@pytest.mark.parametrize("code", good_list)
def test_good_init_funcs(code):
    assert compile_code(code) is not None


fail_list = [
    """
@internal
def __init__():
    pass
    """,
    """
@deploy
@view
def __init__():
    pass
    """,
    """
@deploy
@pure
def __init__():
    pass
    """,
    """
@deploy
def some_function():  # for now, only __init__() functions can be marked @deploy
    pass
    """,
]


@pytest.mark.parametrize("code", fail_list)
def test_bad_init_funcs(code):
    with pytest.raises(FunctionDeclarationException):
        compile_code(code)
