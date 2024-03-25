import dataclasses
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


# TODO: use StringEnum (requires refactoring vyper.utils to avoid import cycle)
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

    def __str__(self):
        return self._name_.lower()


@dataclass
class Settings:
    compiler_version: Optional[str] = None
    optimize: Optional[OptimizationLevel] = None
    evm_version: Optional[str] = None
    experimental_codegen: Optional[bool] = None

    def as_cli(self):
        ret = []
        if self.optimize is not None:
            ret.append(" --optimize " + str(self.optimize))
        if self.experimental_codegen is True:
            ret.append(" --experimental-codegen")
        if self.evm_version is not None:
            ret.append(" --evm-version " + self.evm_version)

        return " ".join(ret)

    def as_dict(self):
        ret = dataclasses.asdict(self)
        # compiler_version is not a compiler input, it can only come from
        # source code pragma.
        ret.pop("compiler_version", None)
        ret = {k: v for (k, v) in ret.items() if v is not None}
        if "optimize" in ret:
            ret["optimize"] = str(ret["optimize"])
        return ret


_DEBUG = False


def _is_debug_mode():
    global _DEBUG
    return _DEBUG


def _set_debug_mode(dbg: bool = False) -> None:
    global _DEBUG
    _DEBUG = dbg
