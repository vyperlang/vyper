import io
import re
from tokenize import COMMENT, NAME, OP, TokenError, TokenInfo, tokenize, untokenize
from typing import Any

from packaging.specifiers import InvalidSpecifier, SpecifierSet

from vyper.compiler.settings import OptimizationLevel, Settings

# seems a bit early to be importing this but we want it to validate the
# evm-version pragma
from vyper.evm.opcodes import EVM_VERSIONS
from vyper.exceptions import StructureException, SyntaxException, VersionException
from vyper.typing import ModificationOffsets, ParserPosition


def validate_version_pragma(version_str: str, start: ParserPosition) -> None:
    """
    Validates a version pragma directive against the current compiler version.
    """
    from vyper import __version__

    if len(version_str) == 0:
        raise VersionException("Version specification cannot be empty", start)

    # X.Y.Z or vX.Y.Z => ==X.Y.Z, ==vX.Y.Z
    if re.match("[v0-9]", version_str):
        version_str = "==" + version_str
    # convert npm to pep440
    version_str = re.sub("^\\^", "~=", version_str)

    try:
        spec = SpecifierSet(version_str)
    except InvalidSpecifier:
        raise VersionException(
            f'Version specification "{version_str}" is not a valid PEP440 specifier', start
        )

    if not spec.contains(__version__, prereleases=True):
        raise VersionException(
            f'Version specification "{version_str}" is not compatible '
            f'with compiler version "{__version__}"',
            start,
        )


# compound statements that are replaced with `class`
# TODO remove enum in favor of flag
VYPER_CLASS_TYPES = {"flag", "enum", "event", "interface", "struct"}

# simple statements or expressions that are replaced with `yield`
VYPER_EXPRESSION_TYPES = {"log"}


def pre_parse(code: str) -> tuple[Settings, dict[int, dict[str, Any]], ModificationOffsets, str]:
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
    dict[int, dict[str, Any]]
        A mapping of line numbers of `For` nodes to the type annotation of the iterator
    str
        Reformatted python source string.
    """
    result = []
    modification_offsets: ModificationOffsets = {}
    settings = Settings()
    loop_var_annotation_tokens = {}

    try:
        code_bytes = code.encode("utf-8")
        token_list = list(tokenize(io.BytesIO(code_bytes).readline))

        is_for_loop = False
        after_loop_var = False
        loop_var_annotation: list = []

        for i in range(len(token_list)):
            token = token_list[i]
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
                    validate_version_pragma(compiler_version, start)
                    settings.compiler_version = compiler_version

                if contents.startswith("pragma "):
                    pragma = contents.removeprefix("pragma ").strip()
                    if pragma.startswith("version "):
                        if settings.compiler_version is not None:
                            raise StructureException("pragma version specified twice!", start)
                        compiler_version = pragma.removeprefix("version ").strip()
                        validate_version_pragma(compiler_version, start)
                        settings.compiler_version = compiler_version

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
                            raise StructureException("Invalid evm version: `{evm_version}`", start)
                        settings.evm_version = evm_version

                    else:
                        raise StructureException(f"Unknown pragma `{pragma.split()[0]}`")

            if typ == NAME and string in ("class", "yield"):
                raise SyntaxException(
                    f"The `{string}` keyword is not allowed. ", code, start[0], start[1]
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

            if typ == NAME and string == "for":
                is_for_loop = True

            if is_for_loop:
                if typ == NAME and string == "in":
                    loop_var_annotation_tokens[start[0]] = loop_var_annotation

                    is_for_loop = False
                    after_loop_var = False
                    loop_var_annotation = []

                elif (typ, string) == (OP, ":"):
                    after_loop_var = True
                    continue

                elif after_loop_var and not (typ == NAME and string == "for"):
                    loop_var_annotation.extend(toks)
                    continue

            result.extend(toks)
    except TokenError as e:
        raise SyntaxException(e.args[0], code, e.args[1][0], e.args[1][1]) from e

    loop_var_annotations: dict[int, dict[str, Any]] = {}
    for k, v in loop_var_annotation_tokens.items():
        updated_v = untokenize(v)
        updated_v = updated_v.replace("\\", "")
        updated_v = updated_v.replace("\n", "")
        import textwrap

        loop_var_annotations[k] = {"source_code": textwrap.dedent(updated_v)}

    return settings, loop_var_annotations, modification_offsets, untokenize(result).decode("utf-8")
