import sys

import pytest

from tests.ast_utils import deepequals
from vyper.ast.parse import parse_to_ast
from vyper.compiler import compile_code
from vyper.exceptions import SyntaxException

_NULL_BYTE_MSG = (
    f"source code {'string ' if sys.version_info < (3, 12) else ''}cannot contain null bytes"
)


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


def test_null_byte_in_main_file():
    code = "a: uint256 = 1\x00\n"
    with pytest.raises(SyntaxException) as exc_info:
        compile_code(code)
    assert exc_info.value.message == _NULL_BYTE_MSG


def test_null_byte_in_imported_module(make_input_bundle):
    lib = """
@internal
def foo() -> uint256:
    return 1\x00
"""
    main = """
import lib

@external
def bar() -> uint256:
    return lib.foo()
"""
    input_bundle = make_input_bundle({"lib.vy": lib})
    with pytest.raises(SyntaxException) as exc_info:
        compile_code(main, input_bundle=input_bundle)
    assert exc_info.value.message == _NULL_BYTE_MSG


def test_null_byte_in_interface_file(make_input_bundle):
    ifoo = """
@external
def foo():
    ...\x00
"""
    main = """
import ifoo

implements: ifoo

@external
def foo():
    pass
"""
    input_bundle = make_input_bundle({"ifoo.vyi": ifoo})
    with pytest.raises(SyntaxException) as exc_info:
        compile_code(main, input_bundle=input_bundle)
    assert exc_info.value.message == _NULL_BYTE_MSG
