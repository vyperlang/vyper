import sys
if (sys.version_info.major, sys.version_info.minor) < (3, 6):
    raise Exception("Requires python3.6+")

from pkg_resources import get_distribution

__version__ = get_distribution('viper').version
