import sys

import pytest

from tests.ast_utils import deepequals
from vyper.ast.parse import parse_to_ast
from vyper.compiler import compile_code
from vyper.exceptions import InvalidLiteral, SyntaxException

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
        "\x0c\n",  # form feed at the start of the file
        "\n\x0c\n",  # form feed on its own line
        "# café\n",  # non-ascii character on a previous line
        "# \U0001f600\n",  # astral (surrogate-pair) character on a previous line
        "# a\x0bb\n",  # vertical tab inside a comment
        "# a\x85b\n",  # U+0085 (next line) inside a comment
        "# a\u2028b\n",  # U+2028 inside a comment
        "# a\u2029b\n",  # U+2029 inside a comment
    ],
)
def test_literal_source_spans_with_offset_shifting_prefixes(prefix):
    # the source spans (and therefore the literal values re-derived from
    # them) must be identical no matter what precedes the literal: CPython
    # reports byte-based column offsets and does not treat "\x0c" or
    # U+2028 as line boundaries, so neither may shift the spans.
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


def test_literal_source_spans_form_feed_at_end_of_line():
    code = (
        f"A: constant(address) = {_HEX_LITERAL}\x0c\n"
        "B: constant(address) = 0x2222222222222222222222222222222222222222\n"
    )
    module_ast = parse_to_ast(code)
    assert [n.value for n in _nodes_of_type(module_ast, "Hex")] == [
        _HEX_LITERAL,
        "0x2222222222222222222222222222222222222222",
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


def test_decimal_and_binary_literal_values_with_form_feed():
    code = (
        "\x0c\n"
        "A: constant(decimal) = 1.5\n"
        "B: constant(bytes4) = 0b11110000111100001111000011110000\n"
    )
    module_ast = parse_to_ast(code)

    (decimal_node,) = _nodes_of_type(module_ast, "Decimal")
    assert decimal_node.node_source_code == "1.5"
    assert str(decimal_node.value) == "1.5"

    (bytes_node,) = _nodes_of_type(module_ast, "Bytes")
    assert bytes_node.node_source_code == "0b11110000111100001111000011110000"
    assert bytes_node.value == b"\xf0\xf0\xf0\xf0"


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
    "char",
    [
        "\x0b",  # vertical tab
        "\x0c",  # form feed
        "\x85",  # next line
        "\u2028",  # line separator
        "\u2029",  # paragraph separator
    ],
)
def test_splitlines_only_characters_in_comments_do_not_shift_spans(char):
    # these characters are line boundaries for str.splitlines() but not
    # for CPython's tokenizer, so they may not shift the line numbers
    # (and spans) of the code that follows them.
    code = (
        f"A: constant(address) = {_HEX_LITERAL}\n"
        f"# comment{char}here\n"
        "B: constant(address) = 0x2222222222222222222222222222222222222222\n"
    )
    module_ast = parse_to_ast(code)
    assert [n.value for n in _nodes_of_type(module_ast, "Hex")] == [
        _HEX_LITERAL,
        "0x2222222222222222222222222222222222222222",
    ]
    assert [n.node_source_code for n in _nodes_of_type(module_ast, "Name")] == [
        "A",
        "constant",
        "address",
        "B",
        "constant",
        "address",
    ]


def test_line_separator_in_string_literal():
    # U+2028 inside a string literal is content, not a line boundary.
    # vyper rejects non-ascii string literals, but the rejection must
    # point at the right place: the node's span must slice exactly the
    # literal from the source, on the line the parser reports.
    code = "\x0c\n" + 'A: constant(String[4]) = "a\u2028b"\n'
    with pytest.raises(InvalidLiteral) as exc_info:
        parse_to_ast(code)

    (annotation,) = exc_info.value.annotations
    assert annotation.lineno == 2
    assert annotation.node_source_code == '"a\u2028b"'


def test_form_feed_contract_compiles_to_same_runtime_bytecode():
    code = (
        f"A: constant(address) = {_HEX_LITERAL}\n\n@external\ndef get() -> address:\n    return A\n"
    )
    out = compile_code(code, output_formats=["bytecode_runtime"])
    out_ff = compile_code("\x0c\n" + code, output_formats=["bytecode_runtime"])
    assert out_ff["bytecode_runtime"] == out["bytecode_runtime"]


def test_escaped_form_feed_in_bytes_literal_allowed():
    # the escape sequence (four ascii characters in the source text)
    # is ordinary source text and parses as usual.
    code = 'A: constant(bytes1) = b"\\x0c"\n'
    module_ast = parse_to_ast(code)

    (bytes_node,) = _nodes_of_type(module_ast, "Bytes")
    assert bytes_node.value == b"\x0c"
