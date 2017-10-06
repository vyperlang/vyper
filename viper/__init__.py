import sys

from pkg_resources import get_distribution
if (sys.version_info.major, sys.version_info.minor) < (3, 6):
    raise Exception("Requires python3.6+")


__version__ = get_distribution('viper').version
