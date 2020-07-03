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
from vyper.typing import ModificationOffsets, ParserPosition

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

    if len(strict_file_version) == 0:
        raise VersionException(
            "Version specification cannot be empty", start,
        )

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


# compound statements that are replaced with `class`
VYPER_CLASS_TYPES = {
    "event",
    "interface",
    "struct",
}

# simple statements or expressions that are replaced with `yield`
VYPER_EXPRESSION_TYPES = {
    "log",
}


def pre_parse(code: str) -> Tuple[ModificationOffsets, str]:
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "interface", "struct" and "event" keywords into python "class" keyword
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
        Mapping of offsets where source was modified.
    str
        Reformatted python source string.
    """
    result = []
    modification_offsets: ModificationOffsets = {}

    try:
        code_bytes = code.encode("utf-8")
        token_list = list(tokenize(io.BytesIO(code_bytes).readline))

        for i in range(len(token_list)):
            token = token_list[i]
            toks = [token]

            typ = token.type
            string = token.string
            start = token.start
            end = token.end
            line = token.line

            if typ == COMMENT and "@version" in string:
                validate_version_pragma(string[1:], start)

            if typ == NAME and string in ("class", "yield"):
                raise SyntaxException(
                    f"The `{string}` keyword is not allowed. ", code, start[0], start[1],
                )

            if typ == NAME and string == "contract" and start[1] == 0:
                raise SyntaxException(
                    "The `contract` keyword has been deprecated. Please use `interface`",
                    code,
                    start[0],
                    start[1],
                )
            if typ == NAME and string == "log" and token_list[i + 1].string == ".":
                raise SyntaxException(
                    "`log` is no longer an object, please use it as a statement instead",
                    code,
                    start[0],
                    start[1],
                )

            if typ == NAME:
                if string in VYPER_CLASS_TYPES and start[1] == 0:
                    toks = [TokenInfo(NAME, "class", start, end, line)]
                    modification_offsets[start] = f"{string.capitalize()}Def"
                elif string in VYPER_EXPRESSION_TYPES:
                    toks = [TokenInfo(NAME, "yield", start, end, line)]
                    modification_offsets[start] = string.capitalize()

            if (typ, string) == (OP, ";"):
                raise SyntaxException("Semi-colon statements not allowed", code, start[0], start[1])
            result.extend(toks)
    except TokenError as e:
        raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    return modification_offsets, untokenize(result).decode("utf-8")
