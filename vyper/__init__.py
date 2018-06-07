import sys
import pkg_resources


if (sys.version_info.major, sys.version_info.minor) < (3, 6):
    # Can't be tested, as our test harness is using python3.6.
    raise Exception("Requires python3.6+")  # pragma: no cover


try:
    __version__ = pkg_resources.get_distribution('vyper').version
except pkg_resources.DistributionNotFound:
    __version__ = '0.0.0development'
