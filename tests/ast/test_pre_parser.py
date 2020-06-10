import pytest
from pkg_resources.extern import packaging

from vyper import __version__
from vyper.ast.pre_parser import validate_version_pragma
from vyper.exceptions import VersionException

SRC_LINE = (1, 0)  # Dummy source line
version = packaging.version.Version(__version__)._version
bumped_major_version = f"{version.release[0]+1}.0.0"
bumped_minor_version = f"{version.release[0]}.{version.release[1]+1}.0"
bumped_patch_version = f"{version.release[0]}.{version.release[1]}.{version.release[2]+1}"
invalid_version = "0.1"


@pytest.mark.parametrize("file_version", [bumped_patch_version, __version__])
def test_valid_version_pragma(file_version):
    validate_version_pragma(f" @version {file_version}", (SRC_LINE))


@pytest.mark.parametrize("file_version",
                         [bumped_minor_version, bumped_major_version, invalid_version])
def test_invalid_version_pragma(file_version):
    with pytest.raises(VersionException):
        validate_version_pragma(f" @version {file_version}", (SRC_LINE))
