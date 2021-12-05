from vyper.compiler import compile_code, compile_codes  # noqa: F401

try:
    from importlib.metadata import PackageNotFoundError  # type: ignore
    from importlib.metadata import version as _version  # type: ignore
except ModuleNotFoundError:
    from importlib_metadata import PackageNotFoundError  # type: ignore
    from importlib_metadata import version as _version  # type: ignore

try:
    __version__ = _version(__name__)
except PackageNotFoundError:
    from vyper.version import version as __version__
