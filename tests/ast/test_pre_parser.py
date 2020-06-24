import pytest

from vyper.ast.pre_parser import validate_version_pragma
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
    "<=1.0.0 >=0.1.0",
    "0.1.0 - 1.0.0",
    "~0.1.0",
    "0.1",
    "0",
    "*",
    "x",
    "0.x",
    "0.1.x",
    "0.2.0 || 0.1.1",
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
    "==0.1.1",
    "abc",
]


@pytest.mark.parametrize("file_version", valid_versions)
def test_valid_version_pragma(file_version, mock_version):
    mock_version(COMPILER_VERSION)
    validate_version_pragma(f" @version {file_version}", (SRC_LINE))


@pytest.mark.parametrize("file_version", invalid_versions)
def test_invalid_version_pragma(file_version, mock_version):
    mock_version(COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(f" @version {file_version}", (SRC_LINE))


prerelease_valid_versions = [
    "<0.1.1-beta.9",
    "<0.1.1b9",
    "0.1.1b7",
    ">0.1.1b2",
    "<0.1.1-rc.1",
    ">0.1.1a1",
    ">0.1.1-alpha.1",
    "0.1.1a9 - 0.1.1-rc.10",
    "<0.1.1b8",
    "<0.1.1rc1",
]
prerelease_invalid_versions = [
    ">0.1.1-beta.9",
    ">0.1.1b9",
    "0.1.1b8",
    "0.1.1rc2",
    "0.1.1-rc.9 - 0.1.1-rc.10",
    "<0.2.0",
    pytest.param(
        "<0.1.1b1",
        marks=pytest.mark.xfail(
            reason="https://github.com/rbarrois/python-semanticversion/issues/100"
        ),
    ),
    pytest.param(
        "<0.1.1a9",
        marks=pytest.mark.xfail(
            reason="https://github.com/rbarrois/python-semanticversion/issues/100"
        ),
    ),
]


@pytest.mark.parametrize("file_version", prerelease_valid_versions)
def test_prerelease_valid_version_pragma(file_version, mock_version):
    mock_version(PRERELEASE_COMPILER_VERSION)
    validate_version_pragma(f" @version {file_version}", (SRC_LINE))


@pytest.mark.parametrize("file_version", prerelease_invalid_versions)
def test_prerelease_invalid_version_pragma(file_version, mock_version):
    mock_version(PRERELEASE_COMPILER_VERSION)
    with pytest.raises(VersionException):
        validate_version_pragma(f" @version {file_version}", (SRC_LINE))
