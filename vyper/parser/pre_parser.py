import io
import re
from tokenize import (
    COMMENT,
    NAME,
    OP,
    NEWLINE,

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
    line_ofst = 0

    try:
        g = tokenize(io.BytesIO(code.encode('utf-8')).readline)

        for token in g:
            start = (token.start[0] + line_ofst, token.start[1])
            end = (token.end[0] + line_ofst, token.end[1])
            toks = [ token._replace(start=start, end=end) ]
            line = token.line

            if token.type == COMMENT and "@version" in token.string:
                parse_version_pragma(token.string[1:])

            # Alias contract definition to class definition.
            if (token.type, token.string, token.start[1]) == (NAME, "contract", 0):
                line_ofst += 1
                toks = [ TokenInfo(NAME, "@contract", start,start,line),
                         TokenInfo(NEWLINE, "\n", start,start,line) ]
                start = (start[0] + 1, start[1])
                end = (end[0] + 1, end[1])
                toks.append(
                         TokenInfo(token.type, "class", start,end,line))

            # Alias struct definition to class definition.
            if (token.type, token.string, token.start[1]) == (NAME, "struct", 0):
                line_ofst += 1
                toks = [ TokenInfo(NAME, "@struct", start,start,line),
                         TokenInfo(NEWLINE, "\n", start,start,line) ]
                start = (start[0] + 1, start[1])
                end = (end[0] + 1, end[1])
                toks.append(
                         TokenInfo(token.type, "class", start,end,line))

            # Prevent semi-colon line statements.
            if (token.type, token.string) == (OP, ";"):
                raise StructureException("Semi-colon statements not allowed.", token.start)

            result.extend(toks)
    except TokenError as e:
        raise StructureException(e.args[0], e.args[1]) from e

    return untokenize(result).decode('utf-8')
