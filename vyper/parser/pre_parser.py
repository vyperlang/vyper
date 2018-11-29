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
from vyper.exceptions import StructureException
from vyper import __version__


def _parser_version_str(version_str):
    version_regex = re.compile(r'^(\d+\.)?(\d+\.)?(\w*)$')
    if None in version_regex.match(version_str).groups():
        raise Exception('Could not parse given version: %s' % version_str)
    return version_regex.match(version_str).groups()


# Do a version check.
def parse_version_pragma(version_str):
    version_arr = version_str.split('@version')

    file_version = version_arr[1].strip()
    file_major, file_minor, file_patch = _parser_version_str(file_version)
    compiler_major, compiler_minor, compiler_patch = _parser_version_str(__version__)

    if (file_major, file_minor) != (compiler_major, compiler_minor):
        raise Exception('Given version "{}" is not compatible with the compiler ({}): '.format(
            file_version, __version__
        ))


# Minor pre-parser checks.
def pre_parse(code):
    result = []
    replace_mode = None

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
                raise StructureException("The `class` keyword is not allowed. Perhaps you meant `contract` or `struct`?", token.start)
            # `contract xyz` -> `class xyz(__VYPER_ANNOT_CONTRACT__)`
            # `struct xyz` -> `class xyz(__VYPER_ANNOT_STRUCT__)`
            if token.type == NAME and replace_mode:
                toks.extend([
                    TokenInfo(OP, "(", end, end, line),
                    TokenInfo(NAME, replace_mode, end, end, line),
                    TokenInfo(OP, ")", end, end, line),
                ])
                replace_mode = None
            if token.type == NAME and string == "contract" and start[1] == 0:
                replace_mode = "__VYPER_ANNOT_CONTRACT__"
                toks = [TokenInfo(NAME, "class", start, end, line)]
            # In the future, may relax the start-of-line restriction
            if token.type == NAME and string == "struct" and start[1] == 0:
                replace_mode = "__VYPER_ANNOT_STRUCT__"
                toks = [TokenInfo(NAME, "class", start, end, line)]

            # Prevent semi-colon line statements.
            if (token.type, token.string) == (OP, ";"):
                raise StructureException("Semi-colon statements not allowed.", token.start)

            result.extend(toks)
    except TokenError as e:
        raise StructureException(e.args[0], e.args[1]) from e

    return untokenize(result).decode('utf-8')
