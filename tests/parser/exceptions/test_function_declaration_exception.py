import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import FunctionDeclarationException


fail_list = [
    """
@public
def foo(x: int128, x: int128): pass
    """,
    """
@public
def foo(int128: int128):
    pass
    """,
    """
@public
def foo():
    x: int128
@public
def foo():
    y: int128
    """,
    """
@public
def foo():
    self.goo()

@public
def goo():
    self.foo()
    """,
    """
foo: int128

@public
def foo():
    pass
    """,
    """
x: int128

@public
def foo(x: int128): pass
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_function_declaration_exception(bad_code):
        with raises(FunctionDeclarationException):
            compiler.compile(bad_code)
