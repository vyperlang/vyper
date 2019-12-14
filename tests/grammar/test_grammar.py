import textwrap

import hypothesis

from lark import Lark
from lark.indenter import Indenter

from vyper.parser import (
    parser,
)


class PythonIndenter(Indenter):
    NL_type = '_NEWLINE'
    OPEN_PAREN_types = ['LPAR', 'LSQB', 'LBRACE']
    CLOSE_PAREN_types = ['RPAR', 'RSQB', 'RBRACE']
    INDENT_type = '_INDENT'
    DEDENT_type = '_DEDENT'
    tab_len = 8


l = Lark.open(
    'tests/grammar/vyper.lark',
    parser='lalr',
    start='file_input',
    postlex=PythonIndenter()
)


def test_basic_grammar():
    code = """
    a: uint256
    b: uint128
    """
    code_func = """
    @public
    def one_two_three() -> uint256:
        return 123123123
    """

    assert l.parse(textwrap.dedent(code) + "\n")
    assert parser.parse_to_ast(textwrap.dedent(code))

    assert l.parse(textwrap.dedent(code_func) + "\n")
    assert parser.parse_to_ast(textwrap.dedent(code_func))


# @hypothesis.extra.lark.from_lark(

# )
# def test_grammar(code):
#     parser.parse_to_ast(code)
#     pass
