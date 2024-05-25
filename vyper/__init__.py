from pathlib import Path as _Path

from vyper.compiler import compile_code, compile_from_file_input

try:
    from importlib.metadata import PackageNotFoundError  # type: ignore
    from importlib.metadata import version as _version  # type: ignore
except ModuleNotFoundError:
    from importlib_metadata import PackageNotFoundError  # type: ignore
    from importlib_metadata import version as _version  # type: ignore

_commit_hash_file = _Path(__file__).parent.joinpath("vyper_git_commithash.txt")

if _commit_hash_file.exists():
    with _commit_hash_file.open() as fp:
        __commit__ = fp.read()
else:
    __commit__ = "unknown"

try:
    __version__ = _version(__name__)
except PackageNotFoundError:
    from vyper.version import version as __version__

# pep440 version with commit hash
__long_version__ = f"{__version__}+commit.{__commit__}"
