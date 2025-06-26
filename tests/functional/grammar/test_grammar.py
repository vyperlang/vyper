import re
import textwrap

import hypothesis
import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, assume, given
from hypothesis.extra.lark import LarkStrategy

from vyper.ast import Module, parse_to_ast
from vyper.ast.grammar import parse_vyper_source, vyper_grammar
from vyper.ast.pre_parser import PreParser
from vyper.exceptions import SyntaxException


def test_basic_grammar():
    code = """
    a: uint256
    b: uint128
    """
    code_func = """
    @external
    def one_two_three() -> uint256:
        return 123_123_123
    """

    assert parse_vyper_source(code, dedent=True)
    assert parse_to_ast(textwrap.dedent(code))

    assert parse_vyper_source(code_func, dedent=True)
    assert parse_to_ast(textwrap.dedent(code_func))


def test_basic_grammar_empty():
    code = """
    """
    tree = parse_vyper_source(code, dedent=True)
    assert len(tree.children) == 0


@pytest.mark.parametrize(
    "num_literal", ["123_456", "1_000_000", "1_2_3_4_5_6", "1_000", "9_999_999_999_999_999"]
)
def test_decimal_literals_with_underscores(num_literal):
    """Test that decimal literals with underscores parse correctly"""
    code = f"""
@external
def foo() -> uint256:
    return {num_literal}
    """
    assert parse_to_ast(code)


@pytest.mark.parametrize(
    "hex_literal",
    [
        "0x1234_5678",
        "0xFF_FF_FF_FF",
        "0x1_2_3_4",
        "0xdead_beef",
        "0x00_00_00_01",
        "0x_1234_5678",  # underscore after prefix is valid
    ],
)
def test_hex_literals_with_underscores(hex_literal):
    """Test that hex literals with underscores parse correctly"""
    code = f"""
@external
def foo() -> bytes32:
    x: bytes32 = {hex_literal}
    return x
    """
    assert parse_to_ast(code)


@pytest.mark.parametrize(
    "bin_literal", ["0b1010_1010", "0b1111_0000_1111_0000", "0b1010_1010", "0b11111111_11111111"]
)
def test_binary_literals_with_underscores(bin_literal):
    """Test that binary literals with underscores parse correctly"""
    code = f"""
@external
def foo() -> uint256:
    return {bin_literal}
    """
    assert parse_to_ast(code)


@pytest.mark.parametrize("oct_literal", ["0o123_456", "0o7_7_7", "0o1_234_567"])
def test_octal_literals_with_underscores(oct_literal):
    """Test that octal literals with underscores parse correctly"""
    code = f"""
@external
def foo() -> uint256:
    return {oct_literal}
    """
    assert parse_to_ast(code)


@pytest.mark.parametrize(
    "float_literal", ["123_456.789", "1_000.000_1", "0.000_000_1", "1.234_567e10", "1_234.567_8e-5"]
)
def test_float_literals_with_underscores(float_literal):
    """Test that float literals with underscores parse correctly"""
    code = f"""
@external
def foo() -> decimal:
    return {float_literal}
    """
    assert parse_to_ast(code)


@pytest.mark.parametrize(
    "invalid_literal",
    [
        # Trailing underscores
        "123_",
        "0x123_",
        "0b10101010_",
        "0o123_",
        "123.45_",
        # Double underscores
        "10__0",
        "0x12__34",
        "0b10101010__10101010",
        "0o12__34",
        "12.34__56",
    ],
)
def test_invalid_numeric_literals_with_underscores(invalid_literal):
    """Test that invalid numeric literals with underscores fail appropriately"""
    code = f"""
@external
def foo() -> uint256:
    return {invalid_literal}
    """
    with pytest.raises(SyntaxException):
        parse_to_ast(code)


def fix_terminal(terminal: str) -> str:
    # these throw exceptions in the grammar
    for bad in ("\x00", "\\ ", "\x0c", "\x0d"):
        terminal = terminal.replace(bad, " ")
    return terminal


ALLOWED_CHARS = st.characters(codec="ascii", min_codepoint=1)


# With help from hyposmith
# https://github.com/Zac-HD/hypothesmith/blob/master/src/hypothesmith/syntactic.py
class GrammarStrategy(LarkStrategy):
    def __init__(self, grammar, start, explicit_strategies):
        super().__init__(grammar, start, explicit_strategies, alphabet=ALLOWED_CHARS)
        self.terminal_strategies = {
            k: v.map(fix_terminal) for k, v in self.terminal_strategies.items()  # type: ignore
        }

    def draw_symbol(self, data, symbol, draw_state):  # type: ignore
        count = len(draw_state)
        super().draw_symbol(data, symbol, draw_state)
        try:
            compile(
                source="".join(draw_state[count:])
                .replace("contract", "class")
                .replace("struct", "class"),  # HACK: Python ast.parse
                filename="<string>",
                mode="exec",
            )
        except SyntaxError:
            # Python's grammar doesn't actually fully describe the behaviour of the
            # CPython parser and AST-post-processor, so we just filter out errors.
            assume(False)


def from_grammar() -> st.SearchStrategy[str]:
    """
    Generate syntactically-valid Python source code based on the grammar.
    """
    grammar = vyper_grammar()
    explicit_strategies = dict(
        _INDENT=st.just(" " * 4),
        _DEDENT=st.just(""),
        NAME=st.from_regex(r"[a-z_A-Z]+", fullmatch=True).filter(str.isidentifier),
    )
    return GrammarStrategy(grammar, "module", explicit_strategies)


# Avoid examples with *only* single or double quote docstrings
# because they trigger a trivial parser bug
SINGLE_QUOTE_DOCSTRING = re.compile(r"^'''.*'''$")
DOUBLE_QUOTE_DOCSTRING = re.compile(r'^""".*"""$')


def has_no_docstrings(c):
    return not (SINGLE_QUOTE_DOCSTRING.match(c) or DOUBLE_QUOTE_DOCSTRING.match(c))


@pytest.mark.fuzzing
@given(code=from_grammar())
@hypothesis.settings(
    max_examples=500, suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much]
)
def test_grammar_bruteforce(code):
    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code + "\n")
    tree = parse_to_ast(pre_parser.reformatted_code)
    assert isinstance(tree, Module)
