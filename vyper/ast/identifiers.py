import re

from vyper.exceptions import StructureException


def validate_identifier(attr, ast_node=None):
    if not re.match("^[_a-zA-Z][a-zA-Z0-9_]*$", attr):
        raise StructureException(f"'{attr}' contains invalid character(s)", ast_node)
    if attr.lower() in RESERVED_KEYWORDS:
        raise StructureException(f"'{attr}' is a reserved keyword", ast_node)


# https://docs.python.org/3/reference/lexical_analysis.html#keywords
# note we don't technically need to block all python reserved keywords,
# but do it for hygiene
_PYTHON_RESERVED_KEYWORDS = {
    "False",
    "None",
    "True",
    "and",
    "as",
    "assert",
    "async",
    "await",
    "break",
    "class",
    "continue",
    "def",
    "del",
    "elif",
    "else",
    "except",
    "finally",
    "for",
    "from",
    "global",
    "if",
    "import",
    "in",
    "is",
    "lambda",
    "nonlocal",
    "not",
    "or",
    "pass",
    "raise",
    "return",
    "try",
    "while",
    "with",
    "yield",
}
_PYTHON_RESERVED_KEYWORDS = {s.lower() for s in _PYTHON_RESERVED_KEYWORDS}

# Cannot be used for variable or member naming
RESERVED_KEYWORDS = _PYTHON_RESERVED_KEYWORDS | {
    # decorators
    "public",
    "external",
    "nonpayable",
    "constant",
    "immutable",
    "transient",
    "internal",
    "payable",
    "nonreentrant",
    # "class" keywords
    "interface",
    "struct",
    "event",
    "enum",
    "flag"
    # EVM operations
    "unreachable",
    # special functions (no name mangling)
    "init",
    "_init_",
    "___init___",
    "____init____",
    "default",
    "_default_",
    "___default___",
    "____default____",
    # more control flow and special operations
    "range",
    # more special operations
    "indexed",
    # denominations
    "ether",
    "wei",
    "finney",
    "szabo",
    "shannon",
    "lovelace",
    "ada",
    "babbage",
    "gwei",
    "kwei",
    "mwei",
    "twei",
    "pwei",
    # sentinel constant values
    # TODO remove when these are removed from the language
    "zero_address",
    "empty_bytes32",
    "max_int128",
    "min_int128",
    "max_decimal",
    "min_decimal",
    "max_uint256",
    "zero_wei",
}
