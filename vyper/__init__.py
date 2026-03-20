from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from vyper.compiler import compile_code, compile_from_file_input

# pep440 version with commit hash
__long_version__: str
try:
    __long_version__ = _version(__name__)
except PackageNotFoundError:
    from vyper.version import version

    __long_version__ = version

# clean version
__version__ = __long_version__.split("+")[0]
