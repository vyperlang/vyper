import contextlib
import os
from dataclasses import dataclass
from enum import Enum
from typing import Generator, Optional

VYPER_COLOR_OUTPUT = os.environ.get("VYPER_COLOR_OUTPUT", "0") == "1"
VYPER_ERROR_CONTEXT_LINES = int(os.environ.get("VYPER_ERROR_CONTEXT_LINES", "1"))
VYPER_ERROR_LINE_NUMBERS = os.environ.get("VYPER_ERROR_LINE_NUMBERS", "1") == "1"

VYPER_TRACEBACK_LIMIT: Optional[int]

_tb_limit_str = os.environ.get("VYPER_TRACEBACK_LIMIT")
if _tb_limit_str is not None:
    VYPER_TRACEBACK_LIMIT = int(_tb_limit_str)
else:
    VYPER_TRACEBACK_LIMIT = None


class OptimizationLevel(Enum):
    NONE = 1
    GAS = 2
    CODESIZE = 3

    @classmethod
    def from_string(cls, val):
        match val:
            case "none":
                return cls.NONE
            case "gas":
                return cls.GAS
            case "codesize":
                return cls.CODESIZE
        raise ValueError(f"unrecognized optimization level: {val}")

    @classmethod
    def default(cls):
        return cls.GAS


@dataclass
class Settings:
    compiler_version: Optional[str] = None
    optimize: Optional[OptimizationLevel] = None
    evm_version: Optional[str] = None
    experimental_codegen: Optional[bool] = None
    debug: Optional[bool] = None


_settings = None


def get_global_settings() -> Optional[Settings]:
    return _settings


def set_global_settings(new_settings: Optional[Settings]) -> None:
    assert isinstance(new_settings, Settings) or new_settings is None
    # TODO evil circular import
    from vyper.evm.opcodes import DEFAULT_EVM_VERSION, EVM_VERSIONS, set_global_evm_version

    global _settings
    _settings = new_settings

    # set the global evm version so that version_check picks it up.
    # this is a bit spooky, but it's generally always what we want
    # when set_global_settings is called.
    evm_version = DEFAULT_EVM_VERSION
    if new_settings is not None and new_settings.evm_version is not None:
        evm_version = new_settings.evm_version
    set_global_evm_version(EVM_VERSIONS[evm_version])


# could maybe refactor this, but it is easier for now than threading settings
# around everywhere.
@contextlib.contextmanager
def anchor_settings(new_settings: Settings) -> Generator:
    """
    Set the globally available settings for the duration of this context manager
    """
    assert new_settings is not None
    global _settings
    try:
        tmp = get_global_settings()
        set_global_settings(new_settings)
        yield
    finally:
        set_global_settings(tmp)


def _opt_codesize():
    return _settings.optimize == OptimizationLevel.CODESIZE


def _opt_gas():
    return _settings.optimize == OptimizationLevel.GAS


def _opt_none():
    return _settings.optimize == OptimizationLevel.NONE


def _is_debug_mode():
    return get_global_settings().debug
