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
)

VERSION_RE = re.compile(r'^(\d+\.)(\d+\.)(\w*)$')


def _parse_version_str(version_str):
    match = VERSION_RE.match(version_str)

    if match is None:
        raise Exception('Could not parse given version: %s' % version_str)

    return match.groups()


# Do a version check.
def parse_version_pragma(version_str):
    from vyper import (
        __version__,
    )

    version_arr = version_str.split('@version')

    file_version = version_arr[1].strip()
    file_major, file_minor, file_patch = _parse_version_str(file_version)
    compiler_major, compiler_minor, compiler_patch = _parse_version_str(__version__)

    if (file_major, file_minor) != (compiler_major, compiler_minor):
        raise Exception('Given version "{}" is not compatible with the compiler ({}): '.format(
            file_version, __version__
        ))


# Minor pre-parser checks.
def pre_parse(code):
    result = []
    fetch_name = None
    class_names = {}
    class_types = ('contract', 'struct')

    try:
        code = code.encode('utf-8')
        g = tokenize(io.BytesIO(code).readline)

        for token in g:

            toks = [token]
            line = token.line
            start = token.start
            end = token.end
            string = token.string

            if token.type == COMMENT and "@version" in token.string:
                parse_version_pragma(token.string[1:])

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
