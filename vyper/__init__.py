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
    import re

    from vyper.version import version as version_str

    version_str = re.sub(r"\.dev\d+", "", version_str)
    version_str = re.sub(r"\+g([a-f0-9]+).*", r"+commit.\1", version_str)
    __version__ = version_str
