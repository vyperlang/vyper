import sys as _sys
from pathlib import Path as _Path

import pkg_resources as _pkg_resources

from vyper.compiler import compile_code, compile_codes  # noqa: F401

if (_sys.version_info.major, _sys.version_info.minor) < (3, 6):
    # Can't be tested, as our test harness is using python3.6.
    raise Exception("Requires python3.6+")  # pragma: no cover


_version_file = _Path(__file__).parent.joinpath("vyper_git_version.txt")
if _version_file.exists():
    with _version_file.open() as fp:
        __version__, __commit__ = fp.read().split("\n")
        __commit__ = __commit__[:7]
else:
    __commit__ = "unknown"
    try:
        __version__ = _pkg_resources.get_distribution("vyper").version
    except _pkg_resources.DistributionNotFound:
        __version__ = "0.0.0development"
