import textwrap

import hypothesis
from hypothesis import given
from hypothesis.extra.lark import from_lark
import hypothesis.strategies as st
from conftest import get_lark_grammar
from vyper.parser import (
    parser,
)


l = get_lark_grammar()


def test_basic_grammar(lark_grammar):
    code = """
    a: uint256
    b: uint128
    """
    code_func = """
    @public
    def one_two_three() -> uint256:
        return 123123123
    """

    assert lark_grammar.parse(textwrap.dedent(code) + "\n")
    assert parser.parse_to_ast(textwrap.dedent(code))

    assert lark_grammar.parse(textwrap.dedent(code_func) + "\n")
    assert parser.parse_to_ast(textwrap.dedent(code_func))


def test_basic_grammar_empty(lark_grammar):
    code = """
    """
    tree = lark_grammar.parse(textwrap.dedent(code) + "\n")
    assert len(tree.children) == 0

# With help from hyposmith
# https://github.com/Zac-HD/hypothesmith/blob/master/src/hypothesmith/syntactic.py
@given(
    code=from_lark(
        grammar=l,
        explicit=dict(  # from hyposmith
            _INDENT=st.just(" " * 4),
            _DEDENT=st.just(""),
            NAME=st.from_regex(r"[a-z_A-Z]+", fullmatch=True).filter(str.isidentifier),
        )
    )
)
@hypothesis.settings(
    deadline=400,
    max_examples=10000
)
def test_grammar_bruteforce(code):
    tree = parser.parse_to_ast(code + "\n")
    assert isinstance(tree, list)
