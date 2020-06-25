import io
import re
from tokenize import (
    COMMENT,
    NAME,
    OP,
    TokenError,
    TokenInfo,
    tokenize,
    untokenize,
)
from typing import Tuple

from semantic_version import NpmSpec, Version

from vyper.exceptions import SyntaxException, VersionException
from vyper.typing import ClassTypes, ParserPosition

VERSION_ALPHA_RE = re.compile(r"(?<=\d)a(?=\d)")  # 0.1.0a17
VERSION_BETA_RE = re.compile(r"(?<=\d)b(?=\d)")  # 0.1.0b17
VERSION_RC_RE = re.compile(r"(?<=\d)rc(?=\d)")  # 0.1.0rc17


def _convert_version_str(version_str: str) -> str:
    """
    Convert loose version (0.1.0b17) to strict version (0.1.0-beta.17)
    """
    version_str = re.sub(VERSION_ALPHA_RE, "-alpha.", version_str)  # 0.1.0-alpha.17
    version_str = re.sub(VERSION_BETA_RE, "-beta.", version_str)  # 0.1.0-beta.17
    version_str = re.sub(VERSION_RC_RE, "-rc.", version_str)  # 0.1.0-rc.17

    return version_str


def validate_version_pragma(version_str: str, start: ParserPosition) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import __version__

    version_arr = version_str.split("@version")

    raw_file_version = version_arr[1].strip()
    strict_file_version = _convert_version_str(raw_file_version)
    strict_compiler_version = Version(_convert_version_str(__version__))

    try:
        npm_spec = NpmSpec(strict_file_version)
    except ValueError:
        raise VersionException(
            f'Version specification "{raw_file_version}" is not a valid NPM semantic '
            f"version specification",
            start,
        )

    if not npm_spec.match(strict_compiler_version):
        raise VersionException(
            f'Version specification "{raw_file_version}" is not compatible '
            f'with compiler version "{__version__}"',
            start,
        )


VYPER_CLASS_TYPES = {
    "interface",
    "struct",
}


def pre_parse(code: str) -> Tuple[ClassTypes, str]:
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "interface" and "struct" keyword into python "class" keyword
    * Validates "@version" pragma against current compiler version
    * Prevents direct use of python "class" keyword
    * Prevents use of python semi-colon statement separator

    Also returns a mapping of detected interface and struct names to their
    respective vyper class types ("interface" or "struct").

    Parameters
    ----------
    code : str
        The vyper source code to be re-formatted.

    Returns
    -------
    dict
        Mapping of class types for the given source.
    str
        Reformatted python source string.
    """
    result = []
    previous_keyword = None
    class_types: ClassTypes = {}

    try:
        code_bytes = code.encode("utf-8")
        g = tokenize(io.BytesIO(code_bytes).readline)

        for token in g:
            toks = [token]

            typ = token.type
            string = token.string
            start = token.start
            end = token.end
            line = token.line

            if typ == COMMENT and "@version" in string:
                validate_version_pragma(string[1:], start)

            if typ == NAME and string == "class" and start[1] == 0:
                raise SyntaxException(
                    "The `class` keyword is not allowed. "
                    "Perhaps you meant `interface` or `struct`?",
                    code,
                    start[0],
                    start[1],
                )

            # Make note of interface or struct name along with the type keyword
            # that preceded it
            if typ == NAME and previous_keyword is not None:
                class_types[string] = previous_keyword
                previous_keyword = None

            # Translate vyper-specific class keywords into python "class"
            # keyword
            if typ == NAME and string in VYPER_CLASS_TYPES and start[1] == 0:
                toks = [TokenInfo(NAME, "class", start, end, line)]
                previous_keyword = string

            if (typ, string) == (OP, ";"):
                raise SyntaxException("Semi-colon statements not allowed", code, start[0], start[1])
            result.extend(toks)
    except TokenError as e:
        raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    return class_types, untokenize(result).decode("utf-8")
