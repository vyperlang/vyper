from pathlib import Path

import pytest

from vyper import compile_code
from vyper.ast.pre_parser import PreParser, validate_version_pragma
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import PragmaException, VersionException

SRC_LINE = (1, 0)  # Dummy source line
COMPILER_VERSION = "0.1.1"
PRERELEASE_COMPILER_VERSION = "0.1.1b7"


@pytest.fixture
def mock_version(monkeypatch):
    def set_version(version):
        monkeypatch.setattr("vyper.__version__", version)

    return set_version


valid_versions = [
    "0.1.1",
    ">0.0.1",
    "^0.1.0",
    "<=1.0.0,>=0.1.0",
    # "0.1.0 - 1.0.0",
    "~=0.1.0",
]
invalid_versions = [
    "0.1.0",
    ">1.0.0",
    "^0.2.0",
    "<=0.0.1 >=1.1.1",
    "1.0.0 - 2.0.0",
    "~1.0.0",
    "0.2",
    "1",
    "1.x",
    "0.2.x",
    "0.2.0 || 0.1.3",
    "abc",
]


@pytest.mark.parametrize("file_version", valid_versions)
def test_valid_version_pragma(file_version, mock_version):
    mock_version(COMPILER_VERSION)
    validate_version_pragma(f"{file_version}", (file_version, *SRC_LINE))


@pytest.mark.parametrize("file_version", invalid_versions)
def test_invalid_version_pragma(file_version, mock_version):
    mock_version(COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(f"{file_version}", (file_version, *SRC_LINE))


def test_invalid_version_contains_file(mock_version):
    mock_version(COMPILER_VERSION)
    with pytest.raises(VersionException, match=r'contract "mock\.vy:\d+"'):
        compile_code("# pragma version ^0.3.10", resolved_path=Path("mock.vy"))


def test_imported_invalid_version_contains_correct_file(
    mock_version, make_input_bundle, chdir_tmp_path
):
    code_a = "# pragma version ^0.3.10"
    code_b = "import A"
    input_bundle = make_input_bundle({"A.vy": code_a, "B.vy": code_b})
    mock_version(COMPILER_VERSION)

    with pytest.raises(VersionException, match=r'contract "A\.vy:\d+"'):
        compile_code(code_b, input_bundle=input_bundle)


prerelease_valid_versions = [
    "<0.1.1-beta.9",
    "<0.1.1b9",
    "0.1.1b7",
    ">0.1.1b2",
    "<0.1.1-rc.1",
    ">0.1.1a1",
    ">0.1.1-alpha.1",
    ">=0.1.1a9,<=0.1.1-rc.10",
    "<0.1.1b8",
    "<0.1.1rc1",
    "<0.2.0",
]
prerelease_invalid_versions = [
    ">0.1.1-beta.9",
    ">0.1.1b9",
    "0.1.1b8",
    "0.1.1rc2",
    "0.1.1-rc.9 - 0.1.1-rc.10",
    "<0.1.1b1",
    "<0.1.1a9",
]


@pytest.mark.parametrize("file_version", prerelease_valid_versions)
def test_prerelease_valid_version_pragma(file_version, mock_version):
    mock_version(PRERELEASE_COMPILER_VERSION)
    validate_version_pragma(file_version, (file_version, *SRC_LINE))


@pytest.mark.parametrize("file_version", prerelease_invalid_versions)
def test_prerelease_invalid_version_pragma(file_version, mock_version):
    mock_version(PRERELEASE_COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(file_version, (file_version, *SRC_LINE))


pragma_examples = [
    (
        """
    """,
        Settings(),
        Settings(optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma optimize codesize
    """,
        Settings(optimize=OptimizationLevel.CODESIZE),
        None,
    ),
    (
        """
    #pragma optimize none
    """,
        Settings(optimize=OptimizationLevel.NONE),
        None,
    ),
    (
        """
    #pragma optimize gas
    """,
        Settings(optimize=OptimizationLevel.GAS),
        None,
    ),
    (
        """
    #pragma version 0.3.10
    """,
        Settings(compiler_version="0.3.10"),
        Settings(optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai"),
        Settings(evm_version="shanghai", optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma optimize codesize
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai", optimize=OptimizationLevel.CODESIZE),
        None,
    ),
    (
        """
    #pragma version 0.3.10
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai", compiler_version="0.3.10"),
        Settings(evm_version="shanghai", optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma version 0.3.10
    #pragma optimize gas
    """,
        Settings(compiler_version="0.3.10", optimize=OptimizationLevel.GAS),
        Settings(optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma version 0.3.10
    #pragma evm-version shanghai
    #pragma optimize gas
    """,
        Settings(compiler_version="0.3.10", optimize=OptimizationLevel.GAS, evm_version="shanghai"),
        Settings(optimize=OptimizationLevel.GAS, evm_version="shanghai"),
    ),
]


@pytest.mark.parametrize("code, pre_parse_settings, compiler_data_settings", pragma_examples)
def test_parse_pragmas(code, pre_parse_settings, compiler_data_settings, mock_version):
    mock_version("0.3.10")
    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code)

    assert pre_parser.settings == pre_parse_settings

    compiler_data = CompilerData(code)

    # check what happens after CompilerData constructor
    if compiler_data_settings is None:
        # None is sentinel here meaning that nothing changed
        compiler_data_settings = pre_parse_settings

    # experimental_codegen is False by default
    compiler_data_settings.experimental_codegen = False

    assert compiler_data.settings == compiler_data_settings


pragma_venom = [
    """
    #pragma venom-experimental
    """,
    """
    #pragma experimental-codegen
    """,
]


@pytest.mark.parametrize("code", pragma_venom)
def test_parse_venom_pragma(code):
    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code)
    assert pre_parser.settings.experimental_codegen is True

    compiler_data = CompilerData(code)
    assert compiler_data.settings.experimental_codegen is True


invalid_pragmas = [
    # evm-versionnn
    """
# pragma evm-versionnn cancun
    """,
    # bad fork name
    """
# pragma evm-version cancunn
    """,
    # oppptimize
    """
# pragma oppptimize codesize
    """,
    # ggas
    """
# pragma optimize ggas
    """,
    # double specified
    """
# pragma optimize gas
# pragma optimize codesize
    """,
    # double specified
    """
# pragma evm-version cancun
# pragma evm-version shanghai
    """,
    # duplicate setting of venom
    """
    #pragma venom-experimental
    #pragma experimental-codegen
    """,
    """
    #pragma venom-experimental
    #pragma venom-experimental
    """,
]


@pytest.mark.parametrize("code", invalid_pragmas)
def test_invalid_pragma(code):
    with pytest.raises(PragmaException):
        PreParser(is_interface=False).parse(code)


# pragmas which are not in the canonical `# pragma <directive>` form
# must not be silently treated as ordinary comments
malformed_pragmas = [
    "# pragma\tnonreentrancy on",
    "# \u200bpragma nonreentrancy on",  # zero-width space
    "#\u200b pragma nonreentrancy on",
    "# \u2060pragma nonreentrancy on",  # word joiner
    "## pragma nonreentrancy on",
    "# # pragma nonreentrancy on",
    "# Pragma nonreentrancy on",
    "# PRAGMA nonreentrancy on",
    "# pragma",
    "x: uint256  # Pragma nonreentrancy on",
    "## @version ^0.4.0",
    "# @Version ^0.4.0",
    "# \u200b@version ^0.4.0",
    # a coding cookie must not change how the (already decoded) source is read
    "# coding: latin-1\n# \u200bpragma nonreentrancy on",
]


@pytest.mark.parametrize("code", malformed_pragmas)
def test_malformed_pragma(code):
    with pytest.raises(PragmaException, match="Malformed pragma"):
        PreParser(is_interface=False).parse(code)


# comments with bidi embedding/override/isolate controls can render as a
# pragma while being parsed as something else ("trojan source")
bidi_comments = [
    # renders as `# pragma nonreentrancy on` in bidi-aware editors
    "# \u202eno ycnartneernon amgarp\u202c",
    "# pragma nonreentrancy on \u2067\u2069",
    "x: uint256  # \u202a\u202c",
    "# \u202b\u202d\u2066\u2068\u2069",
    "# coding: latin-1\n# \u202eno ycnartneernon amgarp\u202c",
]


@pytest.mark.parametrize("code", bidi_comments)
def test_bidi_control_in_comment(code):
    with pytest.raises(PragmaException, match="Bidirectional control character"):
        PreParser(is_interface=False).parse(code)


# other control characters can also change how a comment renders
control_char_comments = [
    # renders as `# pragma nonreentrancy on` in a terminal
    "##\x08 pragma nonreentrancy on",
    "# \x1b[2K",  # escape
    "# \x7f",  # DEL
    "# \x9b",  # C1 control
]


@pytest.mark.parametrize("code", control_char_comments)
def test_control_char_in_comment(code):
    with pytest.raises(PragmaException, match="Control character in comment"):
        PreParser(is_interface=False).parse(code)


@pytest.mark.parametrize(
    "code",
    [
        "\ufeff# pragma nonreentrancy on",  # BOM
        "# coding: latin-1\n# pragma nonreentrancy on",
        "# -*- coding: utf-8 -*-\n#\tpragma nonreentrancy on",
    ],
)
def test_pragma_with_bom_or_coding_cookie(code):
    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code)
    assert pre_parser.settings.nonreentrancy_by_default is True


def test_malformed_nonreentrancy_pragma_compile():
    # a misspelled `nonreentrancy` pragma must not compile to a contract
    # without reentrancy guards
    code = """
# Pragma nonreentrancy on

interface Foo:
    def bar(): nonpayable

x: uint256

@external
def f(a: address):
    self.x = 1
    extcall Foo(a).bar()
    """
    with pytest.raises(PragmaException, match="Malformed pragma"):
        compile_code(code)

    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code.replace("# Pragma", "# pragma"))
    assert pre_parser.settings.nonreentrancy_by_default is True


# comments which merely mention pragmas are still ordinary comments
non_pragma_comments = [
    "# pragmatic",
    "# pragmas are documented in structure-of-a-contract.rst",
    "# pragma: nocover",
    "# the pragma nonreentrancy on line 1",
    "# a\tcomment with a tab",
    "#",
]


@pytest.mark.parametrize("code", non_pragma_comments)
def test_non_pragma_comment(code):
    pre_parser = PreParser(is_interface=False)
    pre_parser.parse(code)
    assert pre_parser.settings == Settings()


def test_version_exception_in_import(make_input_bundle):
    lib_version = "~=0.3.10"
    lib = f"""
#pragma version {lib_version}

@external
def foo():
    pass
    """

    code = """
import lib

uses: lib

@external
def bar():
    pass
    """
    input_bundle = make_input_bundle({"lib.vy": lib})

    with pytest.raises(VersionException) as excinfo:
        compile_code(code, input_bundle=input_bundle)
    annotation = excinfo.value.annotations[0]
    assert annotation.lineno == 2
    assert annotation.col_offset == 0
    assert annotation.full_source_code == lib
