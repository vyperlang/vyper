import sys

import pytest

from tests.ast_utils import deepequals
from vyper.ast.parse import parse_to_ast
from vyper.exceptions import CompilerPanic, SyntaxException


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


@pytest.mark.parametrize(
    "typ", ["uint256" + "[1]" * 500, "DynArray[" * 200 + "uint256" + ", 2]" * 200]
)
def test_deeply_nested_type_raises_compiler_panic(typ):
    # py-evm, py_ecc raise the recursion limit (on import)
    # so we lower it here so that it matches CPython's default
    # hence restoring the behavior as it would be for users
    old_limit = sys.getrecursionlimit()
    sys.setrecursionlimit(1000)
    try:
        code = f"x: {typ}"
        with pytest.raises(CompilerPanic) as excinfo:
            parse_to_ast(code)
        assert excinfo.value.message.startswith(
            "unhandled exception during parsing: "
            "RecursionError: maximum recursion depth exceeded"
        )
    finally:
        sys.setrecursionlimit(old_limit)
