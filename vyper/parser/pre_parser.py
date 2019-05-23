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
from typing import (
    Sequence,
    Tuple,
)

from vyper.exceptions import (
    StructureException,
    VersionException,
)
from vyper.typing import (
    ClassTypes,
    ParserPosition,
)

VERSION_RE = re.compile(r'^(\d+\.)(\d+\.)(\w*)$')


def _parse_version_str(version_str: str, start: ParserPosition) -> Sequence[str]:
    match = VERSION_RE.match(version_str)

    if match is None:
        raise VersionException(
            f'Could not parse given version string "{version_str}"',
            start,
        )

    return match.groups()


def validate_version_pragma(version_str: str, start: ParserPosition) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import (
        __version__,
    )

    version_arr = version_str.split('@version')

    file_version = version_arr[1].strip()
    file_major, file_minor, file_patch = _parse_version_str(file_version, start)
    compiler_major, compiler_minor, compiler_patch = _parse_version_str(__version__, start)

    if (file_major, file_minor) != (compiler_major, compiler_minor):
        raise VersionException(
            f'File version "{file_version}" is not compatible '
            f'with compiler version "{__version__}"',
            start,
        )


VYPER_CLASS_TYPES = (
    'contract',
    'struct',
)


def pre_parse(code: str) -> Tuple[ClassTypes, str]:
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "contract" and "struct" keyword into python "class" keyword
    * Validates "@version" pragma against current compiler version
    * Prevents direct use of python "class" keyword
    * Prevents use of python semi-colon statement separator

    Also returns a mapping of detected contract and struct names to their
    respective vyper class types ("contract" or "struct").

    :param code: The vyper source code to be re-formatted.
    :return: A tuple including the class type mapping and the reformatted python
        source string.
    """
    result = []
    previous_keyword = None
    class_types: ClassTypes = {}

    try:
        code_bytes = code.encode('utf-8')
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
                raise StructureException(
                    "The `class` keyword is not allowed. Perhaps you meant `contract` or `struct`?",
                    start,
                )

            # Make note of contract or struct name along with the type keyword
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
                raise StructureException("Semi-colon statements not allowed.", start)

            result.extend(toks)
    except TokenError as e:
        raise StructureException(e.args[0], e.args[1]) from e

    return class_types, untokenize(result).decode('utf-8')
