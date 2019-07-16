import hashlib as _hashlib
import os as _os
from pathlib import (
    Path as _Path,
)
import sys as _sys

import pkg_resources as _pkg_resources

from vyper.compiler import (  # noqa
    compile_code,
    compile_codes,
)

if (_sys.version_info.major, _sys.version_info.minor) < (3, 6):
    # Can't be tested, as our test harness is using python3.6.
    raise Exception("Requires python3.6+")  # pragma: no cover


def _get_version_hash(root: _Path) -> str:
    m = _hashlib.sha1()
    for dirname, _, file_list in _os.walk(root):
        for fname in file_list:
            if fname[-3:] == '.py':
                with open(_Path(dirname).joinpath(fname), 'rb') as f:
                    m.update(f.read())
    return m.digest().hex()


try:
    __version__ = _pkg_resources.get_distribution('vyper').version
except _pkg_resources.DistributionNotFound:
    __version__ = '0.0.0development'


# Append first 5 chars of sha1 hash of all files in package directory
# NOTE: First 5 chars used so as not to confuse with git commit hash
# NOTE: This should only be used a sanity check, please check git commits
#       if unsure of version correctness
extended_version = '{}+sha1.{}'.format(__version__,
                                       _get_version_hash(_Path(__file__).parent)[:5])
