import os
from dataclasses import dataclass
from enum import Enum
from typing import Optional

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


_DEBUG = False


def _is_debug_mode():
    global _DEBUG
    return _DEBUG


def _set_debug_mode(dbg: bool = False) -> None:
    global _DEBUG
    _DEBUG = dbg
