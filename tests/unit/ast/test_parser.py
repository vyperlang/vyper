import sys

import pytest

from tests.ast_utils import deepequals
from vyper.ast.parse import parse_to_ast
from vyper.compiler import compile_code
from vyper.exceptions import SyntaxException

if sys.version_info < (3, 12):
    _NULL_BYTE_MSG = "source code string cannot contain null bytes"
else:
    _NULL_BYTE_MSG = "source code cannot contain null bytes"


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


_HEX_LITERAL = "0x1111111111111111111111111111111111111111"


def _nodes_of_type(module_ast, ast_type):
    return [n for n in module_ast.get_descendants() if n.ast_type == ast_type]


@pytest.mark.parametrize(
    "prefix",
    [
        "# café\n",  # non-ascii character on a previous line
        "# \U0001f600\n",  # astral (surrogate-pair) character on a previous line
    ],
)
def test_literal_source_spans_with_offset_shifting_prefixes(prefix):
    # the source spans (and therefore the literal values re-derived from
    # them) must be identical no matter what precedes the literal: CPython
    # reports byte-based column offsets, so a multi-byte character earlier
    # in the source may not shift the spans.
    code = prefix + f"A: constant(address) = {_HEX_LITERAL}\n"
    module_ast = parse_to_ast(code)

    (hex_node,) = _nodes_of_type(module_ast, "Hex")
    assert hex_node.node_source_code == _HEX_LITERAL
    assert hex_node.value == _HEX_LITERAL

    # every name must slice exactly its own identifier as well
    assert [n.node_source_code for n in _nodes_of_type(module_ast, "Name")] == [
        "A",
        "constant",
        "address",
    ]


def test_literal_source_span_nfkc_identifier():
    # U+FB01 (3 utf-8 bytes, 1 character) NFKC-normalizes to the ascii name
    # "fi"; the byte-based column offsets it produces must not displace the
    # spans of the nodes that follow it on the same line.
    code = f"ﬁ: constant(address) = {_HEX_LITERAL}\n"
    module_ast = parse_to_ast(code)

    (hex_node,) = _nodes_of_type(module_ast, "Hex")
    assert hex_node.node_source_code == _HEX_LITERAL
    assert hex_node.value == _HEX_LITERAL
    assert _nodes_of_type(module_ast, "Name")[0].node_source_code == "ﬁ"


def test_decimal_and_binary_literal_values_after_multibyte_char():
    # the decimal value is re-derived from the sliced source text, so a
    # multi-byte character earlier on the line must not displace its span
    code = (
        "ﬁ: constant(decimal) = 1.5\n" "B: constant(bytes4) = 0b11110000111100001111000011110000\n"
    )
    module_ast = parse_to_ast(code)

    (decimal_node,) = _nodes_of_type(module_ast, "Decimal")
    assert decimal_node.node_source_code == "1.5"
    assert str(decimal_node.value) == "1.5"

    (bytes_node,) = _nodes_of_type(module_ast, "Bytes")
    assert bytes_node.node_source_code == "0b11110000111100001111000011110000"
    assert bytes_node.value == b"\xf0\xf0\xf0\xf0"


@pytest.mark.parametrize(
    "char,code_point",
    [
        ("\x0b", "U+000B"),  # vertical tab
        ("\x0c", "U+000C"),  # form feed
        ("\x85", "U+0085"),  # next line
        ("\u2028", "U+2028"),  # line separator
        ("\u2029", "U+2029"),  # paragraph separator
    ],
)
def test_forbidden_source_characters_rejected(char, code_point):
    # these characters are line boundaries for str.splitlines() but not
    # for CPython's tokenizer, so they are forbidden in vyper source
    # instead of being accounted for in the span computation.
    code = f"A: constant(address) = {_HEX_LITERAL}\n# comment{char}here\n"
    with pytest.raises(SyntaxException) as exc_info:
        parse_to_ast(code)
    assert code_point in exc_info.value.message


def test_forbidden_character_at_start_of_file():
    code = f"\x0c\nA: constant(address) = {_HEX_LITERAL}\n"
    with pytest.raises(SyntaxException) as exc_info:
        parse_to_ast(code)
    annotation = exc_info.value.annotations[0]
    assert (annotation.lineno, annotation.col_offset) == (1, 0)


def test_forbidden_character_in_string_literal_rejected():
    code = 'A: constant(String[4]) = "a\u2028b"\n'
    with pytest.raises(SyntaxException) as exc_info:
        parse_to_ast(code)
    assert "U+2028" in exc_info.value.message


def test_form_feed_contract_rejected():
    code = (
        f"A: constant(address) = {_HEX_LITERAL}\n\n@external\ndef get() -> address:\n    return A\n"
    )
    with pytest.raises(SyntaxException):
        compile_code("\x0c\n" + code, output_formats=["bytecode_runtime"])


def test_escaped_form_feed_in_bytes_literal_allowed():
    # only the literal character is forbidden; the escape sequence (four
    # ascii characters in the source text) is fine.
    code = 'A: constant(bytes1) = b"\\x0c"\n'
    module_ast = parse_to_ast(code)

    (bytes_node,) = _nodes_of_type(module_ast, "Bytes")
    assert bytes_node.value == b"\x0c"
