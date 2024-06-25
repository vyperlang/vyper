import enum
import io
import re
from collections import defaultdict
from tokenize import COMMENT, NAME, OP, TokenError, TokenInfo, tokenize, untokenize

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from vyper.compiler.settings import OptimizationLevel, Settings

# seems a bit early to be importing this but we want it to validate the
# evm-version pragma
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import StructureException, SyntaxException, VersionException
from vyper.typing import ModificationOffsets, ParserPosition


def validate_version_pragma(version_str: str, full_source_code: str, start: ParserPosition) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import __version__

    if len(version_str) == 0:
        raise VersionException("Version specification cannot be empty", full_source_code, *start)

    # X.Y.Z or vX.Y.Z => ==X.Y.Z, ==vX.Y.Z
    if re.match("[v0-9]", version_str):
        version_str = "==" + version_str
    # convert npm to pep440
    version_str = re.sub("^\\^", "~=", version_str)

    try:
        spec = SpecifierSet(version_str)
    except InvalidSpecifier:
        raise VersionException(
            f'Version specification "{version_str}" is not a valid PEP440 specifier',
            full_source_code,
            *start,
        )

    if not spec.contains(__version__, prereleases=True):
        raise VersionException(
            f'Version specification "{version_str}" is not compatible '
            f'with compiler version "{__version__}"',
            full_source_code,
            *start,
        )


class ForParserState(enum.Enum):
    NOT_RUNNING = enum.auto()
    START_SOON = enum.auto()
    RUNNING = enum.auto()


# a simple state machine which allows us to handle loop variable annotations
# (which are rejected by the python parser due to pep-526, so we scoop up the
# tokens between `:` and `in` and parse them and add them back in later).
class ForParser:
    def __init__(self, code):
        self._code = code
        self.annotations = {}
        self._current_annotation = None

        self._state = ForParserState.NOT_RUNNING
        self._current_for_loop = None

    def consume(self, token):
        # state machine: we can start slurping tokens soon
        if token.type == NAME and token.string == "for":
            # note: self._state should be NOT_RUNNING here, but we don't sanity
            # check here as that should be an error the parser will handle.
            self._state = ForParserState.START_SOON
            self._current_for_loop = token.start

        if self._state == ForParserState.NOT_RUNNING:
            return False

        # state machine: start slurping tokens
        if token.type == OP and token.string == ":":
            self._state = ForParserState.RUNNING

            # sanity check -- this should never really happen, but if it does,
            # try to raise an exception which pinpoints the source.
            if self._current_annotation is not None:
                raise SyntaxException(
                    "for loop parse error", self._code, token.start[0], token.start[1]
                )

            self._current_annotation = []
            return True  # do not add ":" to tokens.

        # state machine: end slurping tokens
        if token.type == NAME and token.string == "in":
            self._state = ForParserState.NOT_RUNNING
            self.annotations[self._current_for_loop] = self._current_annotation or []
            self._current_annotation = None
            return False

        if self._state != ForParserState.RUNNING:
            return False

        # slurp the token
        self._current_annotation.append(token)
        return True


# compound statements that are replaced with `class`
# TODO remove enum in favor of flag
VYPER_CLASS_TYPES = {
    "flag": "FlagDef",
    "enum": "EnumDef",
    "event": "EventDef",
    "interface": "InterfaceDef",
    "struct": "StructDef",
}

# simple statements that are replaced with `yield`
CUSTOM_STATEMENT_TYPES = {"log": "Log"}
# expression types that are replaced with `await`
CUSTOM_EXPRESSION_TYPES = {"extcall": "ExtCall", "staticcall": "StaticCall"}


def pre_parse(code: str) -> tuple[Settings, ModificationOffsets, dict, str]:
    """
    Re-formats a vyper source string into a python source string and performs
    some validation.  More specifically,

    * Translates "interface", "struct", "flag", and "event" keywords into python "class" keyword
    * Validates "@version" pragma against current compiler version
    * Prevents direct use of python "class" keyword
    * Prevents use of python semi-colon statement separator
    * Extracts type annotation of for loop iterators into a separate dictionary

    Also returns a mapping of detected interface and struct names to their
    respective vyper class types ("interface" or "struct"), and a mapping of line numbers
    of for loops to the type annotation of their iterators.

    Parameters
    ----------
    code : str
        The vyper source code to be re-formatted.

    Returns
    -------
    Settings
        Compilation settings based on the directives in the source code
    ModificationOffsets
        A mapping of class names to their original class types.
    dict[tuple[int, int], list[TokenInfo]]
        A mapping of line/column offsets of `For` nodes to the annotation of the for loop target
    str
        Reformatted python source string.
    """
    result = []
    modification_offsets: ModificationOffsets = {}
    settings = Settings()
    for_parser = ForParser(code)

    _col_adjustments: dict[int, int] = defaultdict(lambda: 0)

    try:
        code_bytes = code.encode("utf-8")
        token_list = list(tokenize(io.BytesIO(code_bytes).readline))

        for token in token_list:
            toks = [token]

            typ = token.type
            string = token.string
            start = token.start
            end = token.end
            line = token.line

            if typ == COMMENT:
                contents = string[1:].strip()
                if contents.startswith("@version"):
                    if settings.compiler_version is not None:
                        raise StructureException("compiler version specified twice!", start)
                    compiler_version = contents.removeprefix("@version ").strip()
                    validate_version_pragma(compiler_version, code, start)
                    settings.compiler_version = compiler_version

                if contents.startswith("pragma "):
                    pragma = contents.removeprefix("pragma ").strip()
                    if pragma.startswith("version "):
                        if settings.compiler_version is not None:
                            raise StructureException("pragma version specified twice!", start)
                        compiler_version = pragma.removeprefix("version ").strip()
                        validate_version_pragma(compiler_version, code, start)
                        settings.compiler_version = compiler_version

                    # TODO: refactor these to something like Settings.from_pragma
                    elif pragma.startswith("optimize "):
                        if settings.optimize is not None:
                            raise StructureException("pragma optimize specified twice!", start)
                        try:
                            mode = pragma.removeprefix("optimize").strip()
                            settings.optimize = OptimizationLevel.from_string(mode)
                        except ValueError:
                            raise StructureException(f"Invalid optimization mode `{mode}`", start)
                    elif pragma.startswith("evm-version "):
                        if settings.evm_version is not None:
                            raise StructureException("pragma evm-version specified twice!", start)
                        evm_version = pragma.removeprefix("evm-version").strip()
                        if evm_version not in EVM_VERSIONS:
                            raise StructureException(f"Invalid evm version: `{evm_version}`", start)
                        settings.evm_version = evm_version
                    elif pragma.startswith("experimental-codegen"):
                        if settings.experimental_codegen is not None:
                            raise StructureException(
                                "pragma experimental-codegen specified twice!", start
                            )
                        settings.experimental_codegen = True
                    elif pragma.startswith("enable-decimals"):
                        if settings.enable_decimals is not None:
                            raise StructureException(
                                "pragma enable_decimals specified twice!", start
                            )
                        settings.enable_decimals = True

                    else:
                        raise StructureException(f"Unknown pragma `{pragma.split()[0]}`")

            if typ == NAME and string in ("class", "yield"):
                raise SyntaxException(
                    f"The `{string}` keyword is not allowed. ", code, start[0], start[1]
                )

            if typ == NAME:
                if string in VYPER_CLASS_TYPES and start[1] == 0:
                    toks = [TokenInfo(NAME, "class", start, end, line)]
                    modification_offsets[start] = VYPER_CLASS_TYPES[string]
                elif string in CUSTOM_STATEMENT_TYPES:
                    new_keyword = "yield"
                    adjustment = len(new_keyword) - len(string)
                    # adjustments for following staticcall/extcall modification_offsets
                    _col_adjustments[start[0]] += adjustment
                    toks = [TokenInfo(NAME, new_keyword, start, end, line)]
                    modification_offsets[start] = CUSTOM_STATEMENT_TYPES[string]
                elif string in CUSTOM_EXPRESSION_TYPES:
                    # a bit cursed technique to get untokenize to put
                    # the new tokens in the right place so that modification_offsets
                    # will work correctly.
                    # (recommend comparing the result of pre_parse with the
                    # source code side by side to visualize the whitespace)
                    new_keyword = "await"
                    vyper_type = CUSTOM_EXPRESSION_TYPES[string]

                    lineno, col_offset = start

                    # fixup for when `extcall/staticcall` follows `log`
                    adjustment = _col_adjustments[lineno]
                    new_start = (lineno, col_offset + adjustment)
                    modification_offsets[new_start] = vyper_type

                    # tells untokenize to add whitespace, preserving locations
                    diff = len(new_keyword) - len(string)
                    new_end = end[0], end[1] + diff

                    toks = [TokenInfo(NAME, new_keyword, start, new_end, line)]

            if (typ, string) == (OP, ";"):
                raise SyntaxException("Semi-colon statements not allowed", code, start[0], start[1])

            if not for_parser.consume(token):
                result.extend(toks)

    except TokenError as e:
        raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    for_loop_annotations = {}
    for k, v in for_parser.annotations.items():
        for_loop_annotations[k] = v.copy()

    return settings, modification_offsets, for_loop_annotations, untokenize(result).decode("utf-8")
