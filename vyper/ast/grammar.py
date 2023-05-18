# EXPERIMENTAL VYPER PARSER
import textwrap

from lark import Lark
from lark.indenter import Indenter


class PythonIndenter(Indenter):
    NL_type = "_NEWLINE"
    OPEN_PAREN_types = ["LPAR", "LSQB", "LBRACE"]
    CLOSE_PAREN_types = ["RPAR", "RSQB", "RBRACE"]
    INDENT_type = "_INDENT"
    DEDENT_type = "_DEDENT"
    tab_len = 4


_lark_grammar = None


def vyper_grammar():
    global _lark_grammar
    if _lark_grammar is None:
        _lark_grammar = Lark.open_from_package(
            "vyper",
            "grammar.lark",
            ("ast/",),
            parser="lalr",
            start="module",
            postlex=PythonIndenter(),
        )
    return _lark_grammar


def parse_vyper_source(code, dedent=False):
    if dedent:
        code = textwrap.dedent(code)
    return vyper_grammar().parse(code + "\n")
