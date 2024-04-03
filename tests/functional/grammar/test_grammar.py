import re
import textwrap

import hypothesis
import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, assume, given
from hypothesis.extra.lark import LarkStrategy

from vyper.ast import Module, parse_to_ast
from vyper.ast.grammar import parse_vyper_source, vyper_grammar
from vyper.ast.pre_parser import pre_parse


def test_basic_grammar():
    code = """
    a: uint256
    b: uint128
    """
    code_func = """
    @external
    def one_two_three() -> uint256:
        return 123123123
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


def fix_terminal(terminal: str) -> bool:
    # these throw exceptions in the grammar
    for bad in ("\x00", "\\ ", "\x0c"):
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
    _, _, _, reformatted_code = pre_parse(code + "\n")
    tree = parse_to_ast(reformatted_code)
    assert isinstance(tree, Module)
