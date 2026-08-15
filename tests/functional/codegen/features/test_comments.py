import pytest

from vyper.compiler import compile_code
from vyper.exceptions import FunctionDeclarationException


def test_comment_test(get_contract):
    comment_test = """
@external
def foo() -> int128:
    # Returns 3
    return 3
    """

    c = get_contract(comment_test)
    assert c.foo() == 3
    print("Passed comment test")


def test_docstring_with_body(get_contract):
    code = """
@external
def bar() -> int128:
    "another docstring"
    return 3
    """
    c = get_contract(code)
    assert c.bar() == 3


def test_docstring_without_body_fails():
    code = """
@external
def foo():
    "notice me"
    """

    with pytest.raises(FunctionDeclarationException) as e:
        compile_code(code)
    assert e.value.message == "Function body cannot consist of only a docstring"
    assert e.value.hint == "add a `pass` statement to the function body"
