import enum
import io
import re
from collections import defaultdict
from tokenize import COMMENT, NAME, OP, STRING, TokenError, TokenInfo, tokenize, untokenize

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from vyper.compiler.settings import OptimizationLevel, Settings

# seems a bit early to be importing this but we want it to validate the
# evm-version pragma
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import PragmaException, SyntaxException, VersionException


def validate_version_pragma(version_str: str, location: tuple[str, int, int]) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import __version__

    if len(version_str) == 0:
        raise VersionException("Version specification cannot be empty", *location)

    # X.Y.Z or vX.Y.Z => ==X.Y.Z, ==vX.Y.Z
    if re.match("[v0-9]", version_str):
        version_str = "==" + version_str
    # convert npm to pep440
    version_str = re.sub("^\\^", "~=", version_str)

    try:
        spec = SpecifierSet(version_str)
    except InvalidSpecifier:
        raise VersionException(
            f'Version specification "{version_str}" is not a valid PEP440 specifier', *location
        )

    if not spec.contains(__version__, prereleases=True):
        raise VersionException(
            f'Version specification "{version_str}" is not compatible '
            f'with compiler version "{__version__}"',
            *location,
        )


def _parse_pragma(comment_contents, settings, is_interface, code, start):
    pragma = comment_contents.removeprefix("pragma ").strip()

    # location for error messages
    location = code, *start

    if pragma.startswith("version "):
        if settings.compiler_version is not None:
            raise PragmaException("pragma version specified twice!", *location)
        compiler_version = pragma.removeprefix("version ").strip()
        validate_version_pragma(compiler_version, location)
        settings.compiler_version = compiler_version
        return

    # TODO: refactor these to something like Settings.from_pragma
    # note similarity to cli arg parsing.
    if pragma.startswith("optimize "):
        if settings.optimize is not None:
            raise PragmaException("pragma optimize specified twice!", *location)
        try:
            mode = pragma.removeprefix("optimize").strip()
            settings.optimize = OptimizationLevel.from_string(mode)
        except ValueError:
            raise PragmaException(f"Invalid optimization mode `{mode}`", *location)
        return

    if pragma.startswith("evm-version "):
        if settings.evm_version is not None:
            raise PragmaException("pragma evm-version specified twice!", *location)
        evm_version = pragma.removeprefix("evm-version").strip()
        if evm_version not in EVM_VERSIONS:
            raise PragmaException(f"Invalid evm version: `{evm_version}`", *location)
        settings.evm_version = evm_version
        return

    if pragma in ("experimental-codegen", "venom-experimental"):
        if settings.experimental_codegen is not None:
            raise PragmaException(
                "pragma experimental-codegen/venom-experimental specified twice!", *location
            )
        settings.experimental_codegen = True
        return

    if pragma == "enable-decimals":
        if settings.enable_decimals is not None:
            raise PragmaException("pragma enable_decimals specified twice!", *location)
        settings.enable_decimals = True
        return

    if pragma.startswith("nonreentrancy "):
        if is_interface:
            raise PragmaException("pragma nonreentrancy not allowed in interface files!", *location)

        if settings.nonreentrancy_by_default is not None:
            raise PragmaException("pragma nonreentrancy specified twice!", *location)
        pragma = pragma.removeprefix("nonreentrancy").strip()
        if pragma not in ("on", "off"):
            raise PragmaException("invalid pragma reentrancy (expected on/off)", *location)
        settings.nonreentrancy_by_default = pragma == "on"
        return

    raise PragmaException(f"Unknown pragma `{pragma.split()[0]}`", *location)  # pragma: nocover


class ParserState(enum.Enum):
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

        self._state = ParserState.NOT_RUNNING
        self._current_for_loop = None

    def consume(self, token):
        # state machine: we can start slurping tokens soon
        if token.type == NAME and token.string == "for":
            # note: self._state should be NOT_RUNNING here, but we don't sanity
            # check here as that should be an error the parser will handle.
            self._state = ParserState.START_SOON
            self._current_for_loop = token.start

        if self._state == ParserState.NOT_RUNNING:
            return False

        # state machine: start slurping tokens
        if token.type == OP and token.string == ":":
            self._state = ParserState.RUNNING

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
            self._state = ParserState.NOT_RUNNING
            self.annotations[self._current_for_loop] = self._current_annotation or []
            self._current_annotation = None
            return False

        if self._state != ParserState.RUNNING:
            return False

        # slurp the token
        self._current_annotation.append(token)
        return True


class HexStringParser:
    def __init__(self):
        self.locations = []
        self._tokens = []
        self._state = ParserState.NOT_RUNNING

    def consume(self, token, result):
        # prepare to check if the next token is a STRING
        if self._state == ParserState.NOT_RUNNING:
            if token.type == NAME and token.string == "x":
                self._tokens.append(token)
                self._state = ParserState.RUNNING
                return True

            return False

        assert self._state == ParserState.RUNNING, "unreachable"

        self._state = ParserState.NOT_RUNNING

        if token.type != STRING:
            # flush the tokens we have accumulated and move on
            result.extend(self._tokens)
            self._tokens = []
            return False

        # mark hex string in locations for later processing
        self.locations.append(token.start)

        # discard the `x` token and apply sanity checks -
        # we should only be discarding one token.
        assert len(self._tokens) == 1
        assert (x_tok := self._tokens[0]).type == NAME and x_tok.string == "x"
        self._tokens = []  # discard tokens

        result.append(token)
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


class PreParser:
    # Compilation settings based on the directives in the source code
    settings: Settings

    # A mapping of offsets to new class names
    keyword_translations: dict[tuple[int, int], str]

    # Map from offsets in the original vyper source code to offsets
    # in the new ("reformatted", i.e. python-compatible) source code
    adjustments: dict[tuple[int, int], int]

    # A mapping of line/column offsets of `For` nodes to the annotation of the for loop target
    for_loop_annotations: dict[tuple[int, int], list[TokenInfo]]
    # A list of line/column offsets of hex string literals
    hex_string_locations: list[tuple[int, int]]
    # Reformatted python source string.
    reformatted_code: str

    def __init__(self, is_interface):
        self._is_interface = is_interface

    def parse(self, code: str):
        """
        Re-formats a vyper source string into a python source string and performs
        some validation.  More specifically,

        * Translates "interface", "struct", "flag", and "event" keywords into python "class" keyword
        * Validates "@version" pragma against current compiler version
        * Prevents direct use of python "class" keyword
        * Prevents use of python semi-colon statement separator
        * Extracts type annotation of for loop iterators into a separate dictionary

        Stores a mapping of detected interface and struct names to their
        respective vyper class types ("interface" or "struct"), and a mapping of line numbers
        of for loops to the type annotation of their iterators.

        Parameters
        ----------
        code : str
            The vyper source code to be re-formatted.
        """
        try:
            self._parse(code)
        except TokenError as e:
            raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    def _parse(self, code: str):
        adjustments: dict = {}
        result: list[TokenInfo] = []
        keyword_translations: dict[tuple[int, int], str] = {}
        settings = Settings()
        for_parser = ForParser(code)
        hex_string_parser = HexStringParser()

        _col_adjustments: dict[int, int] = defaultdict(lambda: 0)

        code_bytes = code.encode("utf-8")
        token_list = list(tokenize(io.BytesIO(code_bytes).readline))

        for token in token_list:
            toks = [token]

            typ = token.type
            string = token.string
            start = token.start
            end = token.end
            line = token.line

            # handle adjustments
            lineno, col = token.start
            adj = _col_adjustments[lineno]
            newstart = lineno, col - adj
            adjustments[lineno, col - adj] = adj

            if typ == COMMENT:
                contents = string[1:].strip()
                if contents.startswith("@version"):
                    if settings.compiler_version is not None:
                        raise PragmaException("compiler version specified twice!", code, *start)
                    compiler_version = contents.removeprefix("@version ").strip()
                    validate_version_pragma(compiler_version, (code, *start))
                    settings.compiler_version = compiler_version

                if contents.startswith("pragma "):
                    _parse_pragma(contents, settings, self._is_interface, code, start)

            if typ == NAME and string in ("class", "yield"):
                raise SyntaxException(
                    f"The `{string}` keyword is not allowed. ", code, start[0], start[1]
                )

            if typ == NAME:
                # see if it's a keyword we need to replace
                new_keyword = None
                if string in VYPER_CLASS_TYPES and start[1] == 0:
                    new_keyword = "class"
                    vyper_type = VYPER_CLASS_TYPES[string]
                elif string in CUSTOM_STATEMENT_TYPES:
                    new_keyword = "yield"
                    vyper_type = CUSTOM_STATEMENT_TYPES[string]
                elif string in CUSTOM_EXPRESSION_TYPES:
                    new_keyword = "await"
                    vyper_type = CUSTOM_EXPRESSION_TYPES[string]

                if new_keyword is not None:
                    keyword_translations[newstart] = vyper_type

                    adjustment = len(string) - len(new_keyword)
                    # adjustments for following tokens
                    lineno, col = start
                    _col_adjustments[lineno] += adjustment

                    # a bit cursed technique to get untokenize to put
                    # the new tokens in the right place so that
                    # `keyword_translations` will work correctly.
                    # (recommend comparing the result of parse with the
                    # source code side by side to visualize the whitespace)
                    toks = [TokenInfo(NAME, new_keyword, start, end, line)]

            if (typ, string) == (OP, ";"):
                raise SyntaxException("Semi-colon statements not allowed", code, start[0], start[1])

            if not for_parser.consume(token) and not hex_string_parser.consume(token, result):
                result.extend(toks)

        for_loop_annotations = {}
        for k, v in for_parser.annotations.items():
            for_loop_annotations[k] = v.copy()

        self.adjustments = adjustments
        self.settings = settings
        self.keyword_translations = keyword_translations
        self.for_loop_annotations = for_loop_annotations
        self.hex_string_locations = hex_string_parser.locations
        self.reformatted_code = untokenize(result).decode("utf-8")
