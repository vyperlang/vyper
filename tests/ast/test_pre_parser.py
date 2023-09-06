import pytest

from vyper.ast.pre_parser import pre_parse, validate_version_pragma
from vyper.compiler.settings import OptimizationLevel, Settings
from vyper.exceptions import VersionException

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
    validate_version_pragma(f"{file_version}", (SRC_LINE))


@pytest.mark.parametrize("file_version", invalid_versions)
def test_invalid_version_pragma(file_version, mock_version):
    mock_version(COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(f"{file_version}", (SRC_LINE))


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
    validate_version_pragma(file_version, (SRC_LINE))


@pytest.mark.parametrize("file_version", prerelease_invalid_versions)
def test_prerelease_invalid_version_pragma(file_version, mock_version):
    mock_version(PRERELEASE_COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(file_version, (SRC_LINE))


pragma_examples = [
    (
        """
    """,
        Settings(),
    ),
    (
        """
    #pragma optimize codesize
    """,
        Settings(optimize=OptimizationLevel.CODESIZE),
    ),
    (
        """
    #pragma optimize none
    """,
        Settings(optimize=OptimizationLevel.NONE),
    ),
    (
        """
    #pragma optimize gas
    """,
        Settings(optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma version 0.3.10
    """,
        Settings(compiler_version="0.3.10"),
    ),
    (
        """
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai"),
    ),
    (
        """
    #pragma optimize codesize
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai", optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma version 0.3.10
    #pragma evm-version shanghai
    """,
        Settings(evm_version="shanghai", compiler_version="0.3.10"),
    ),
    (
        """
    #pragma version 0.3.10
    #pragma optimize gas
    """,
        Settings(compiler_version="0.3.10", optimize=OptimizationLevel.GAS),
    ),
    (
        """
    #pragma version 0.3.10
    #pragma evm-version shanghai
    #pragma optimize gas
    """,
        Settings(compiler_version="0.3.10", optimize=OptimizationLevel.GAS, evm_version="shanghai"),
    ),
]


@pytest.mark.parametrize("code, expected_pragmas", pragma_examples)
def parse_pragmas(code, expected_pragmas):
    pragmas, _, _ = pre_parse(code)
    assert pragmas == expected_pragmas
