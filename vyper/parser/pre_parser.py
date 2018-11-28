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


# State to help map ['contract','struct'] to ['class']
class PreparserState:
    def __init__(self, _struct_names, _contract_names):
        self.struct_names = _struct_names
        self.contract_names = _contract_names

# Minor pre-parser checks.
def pre_parse(code):
    result = []
    state = PreparserState(set(), set())
    vyper_class_detected = None

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

            if vyper_class_detected and token.type == NAME:
                if vyper_class_detected == 'contract':
                    # Prevent collisions between contracts and structs
                    # with same name
                    mangled_name = '__contract_' + string
                    state.contract_names.add(mangled_name)
                    token = TokenInfo(NAME, mangled_name, start, end, line)
                if vyper_class_detected == 'struct':
                    mangled_name = '__struct_' + string
                    state.struct_names.add(mangled_name)
                    token = TokenInfo(NAME, mangled_name, start, end, line)
                vyper_class_detected = None
            if token.type == NAME and string == "contract" and start[1] == 0:
                vyper_class_detected = 'contract'
                token = TokenInfo(NAME, "class", start, end, line)
            # In the future, may relax the start-of-line restriction
            if token.type == NAME and string == "struct" and start[1] == 0:
                vyper_class_detected = 'struct'
                token = TokenInfo(NAME, "class", start, end, line)

            # Prevent semi-colon line statements.
            if (token.type, token.string) == (OP, ";"):
                raise StructureException("Semi-colon statements not allowed.", token.start)

            result.append(token)
    except TokenError as e:
        raise StructureException(e.args[0], e.args[1]) from e

    return (state, untokenize(result).decode('utf-8'))
