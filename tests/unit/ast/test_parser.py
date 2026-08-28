import pytest

from tests.ast_utils import deepequals
from vyper.ast.parse import parse_to_ast
from vyper.exceptions import SyntaxException


def test_ast_equal():
    code = """
@external
def test() -> int128:
    a: uint256 = 100
    return 123
    """

    ast1 = parse_to_ast(code)
    ast2 = parse_to_ast("\n   \n" + code + "\n\n")

    assert deepequals(ast1, ast2)


def test_ast_unequal():
    code1 = """
@external
def test() -> int128:
    a: uint256 = 100
    return 123
    """
    code2 = """
@external
def test() -> int128:
    a: uint256 = 100
    return 121
    """

    ast1 = parse_to_ast(code1)
    ast2 = parse_to_ast(code2)

    assert not deepequals(ast1, ast2)


def test_await_raises_syntax_exception():
    code = """@external
def f():
    await something
"""

    with pytest.raises(SyntaxException) as exc_info:
        parse_to_ast(code)

    exc = exc_info.value
    assert exc.message == "The `await` keyword is not allowed."
    annotation = exc.annotations[0]
    assert (annotation.lineno, annotation.col_offset) == (3, 4)
    assert annotation.full_source_code == code
