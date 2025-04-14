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
    #pragma venom
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
    #pragma venom
    #pragma experimental-codegen
    """,
    """
    #pragma venom
    #pragma venom
    """,
]


@pytest.mark.parametrize("code", invalid_pragmas)
def test_invalid_pragma(code):
    with pytest.raises(PragmaException):
        PreParser(is_interface=False).parse(code)


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
