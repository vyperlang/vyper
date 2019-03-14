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

from vyper.exceptions import (
    StructureException,
    VersionException,
)

VERSION_RE = re.compile(r'^(\d+\.)(\d+\.)(\w*)$')


def _parse_version_str(version_str, start):
    match = VERSION_RE.match(version_str)

    if match is None:
        raise VersionException(
            f'Could not parse given version string "{version_str}"',
            start,
        )

    return match.groups()


def validate_version_pragma(version_str, start):
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


def pre_parse(code):
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "contract" and "struct" keyword into python "class" keyword
    * Validates "@version" pragma against current compiler version
    * Prevents direct use of python "class" keyword
    * Prevents use of python semi-colon statement separator

    Also returns a mapping of contract and struct names to their associated
    class keyword ("contract" or "struct").
    """
    result = []
    fetch_name = None
    class_names = {}
    class_types = ('contract', 'struct')

    try:
        code_bytes = code.encode('utf-8')
        g = tokenize(io.BytesIO(code_bytes).readline)

        for token in g:
            toks = [token]
            line = token.line
            start = token.start
            end = token.end
            string = token.string

            if token.type == COMMENT and "@version" in token.string:
                validate_version_pragma(token.string[1:], start)

            if token.type == NAME and string == "class" and start[1] == 0:
                raise StructureException(
                    "The `class` keyword is not allowed. Perhaps you meant `contract` or `struct`?",
                    token.start,
                )

            if token.type == NAME and fetch_name:
                class_names[string] = fetch_name
                fetch_name = None

            if token.type == NAME and string in class_types and start[1] == 0:
                toks = [TokenInfo(NAME, "class", start, end, line)]
                fetch_name = string

            # Prevent semi-colon line statements.
            if (token.type, token.string) == (OP, ";"):
                raise StructureException("Semi-colon statements not allowed.", token.start)

            result.extend(toks)
    except TokenError as e:
        raise StructureException(e.args[0], e.args[1]) from e

    return class_names, untokenize(result).decode('utf-8')
