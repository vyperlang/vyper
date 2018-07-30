import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException

fail_list = [
    """
@public
def foo(max: int128) -> int128:
    return max
    """,
    """
@public
def foo(len: int128, sha3: int128) -> int128:
    return len+sha3
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_variable_naming_fail(bad_code):

    with raises(FunctionDeclarationException):
        compiler.compile(bad_code)
