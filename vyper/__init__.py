from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from vyper.compiler import compile_code, compile_from_file_input

__version__: str
try:
    __version__ = _version(__name__)
except PackageNotFoundError:
    from vyper.version import version

    __version__ = version

# For backwards compatibility
# TODO: Deprecate
__long_version__ = __version__
