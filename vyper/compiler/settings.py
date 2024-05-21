import contextlib
import dataclasses
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


DEFAULT_ENABLE_DECIMALS = False


@dataclass
class Settings:
    compiler_version: Optional[str] = None
    optimize: Optional[OptimizationLevel] = None
    evm_version: Optional[str] = None
    experimental_codegen: Optional[bool] = None
    debug: Optional[bool] = None
    enable_decimals: Optional[bool] = None

    def __post_init__(self):
        # sanity check inputs
        if self.optimize is not None:
            assert isinstance(self.optimize, OptimizationLevel)
        if self.experimental_codegen is not None:
            assert isinstance(self.experimental_codegen, bool)
        if self.debug is not None:
            assert isinstance(self.debug, bool)
        if self.enable_decimals is not None:
            assert isinstance(self.enable_decimals, bool)

    # CMC 2024-04-10 consider hiding the `enable_decimals` member altogether
    def get_enable_decimals(self) -> bool:
        if self.enable_decimals is None:
            return DEFAULT_ENABLE_DECIMALS
        return self.enable_decimals

    def as_cli(self):
        ret = []
        if self.optimize is not None:
            ret.append(" --optimize " + str(self.optimize))
        if self.experimental_codegen is True:
            ret.append(" --experimental-codegen")
        if self.evm_version is not None:
            ret.append(" --evm-version " + self.evm_version)
        if self.debug is True:
            ret.append(" --debug")
        if self.enable_decimals is True:
            ret.append(" --enable-decimals")

        return "".join(ret)

    def as_dict(self):
        ret = dataclasses.asdict(self)
        # compiler_version is not a compiler input, it can only come from
        # source code pragma.
        ret.pop("compiler_version", None)
        ret = {k: v for (k, v) in ret.items() if v is not None}
        if "optimize" in ret:
            ret["optimize"] = str(ret["optimize"])
        return ret

    @classmethod
    def from_dict(cls, data):
        data = data.copy()
        if "optimize" in data:
            data["optimize"] = OptimizationLevel.from_string(data["optimize"])
        return cls(**data)


def merge_settings(
    one: Settings, two: Settings, lhs_source="compiler settings", rhs_source="source pragma"
) -> Settings:
    def _merge_one(lhs, rhs, helpstr):
        if lhs is not None and rhs is not None and lhs != rhs:
            # aesthetics, conjugate the verbs per english rules
            s1 = "" if lhs_source.endswith("s") else "s"
            s2 = "" if rhs_source.endswith("s") else "s"
            raise ValueError(
                f"settings conflict!\n\n  {lhs_source}: {one}\n  {rhs_source}: {two}\n\n"
                f"({lhs_source} indicate{s1} {helpstr} {lhs}, but {rhs_source} indicate{s2} {rhs}.)"
            )
        return lhs if rhs is None else rhs

    ret = Settings()
    ret.evm_version = _merge_one(one.evm_version, two.evm_version, "evm version")
    ret.optimize = _merge_one(one.optimize, two.optimize, "optimize")
    ret.experimental_codegen = _merge_one(
        one.experimental_codegen, two.experimental_codegen, "experimental codegen"
    )
    ret.enable_decimals = _merge_one(one.enable_decimals, two.enable_decimals, "enable-decimals")

    return ret


# CMC 2024-04-10 do we need it to be Optional?
_settings = None


def get_global_settings() -> Optional[Settings]:
    return _settings


def set_global_settings(new_settings: Optional[Settings]) -> None:
    assert isinstance(new_settings, Settings) or new_settings is None

    global _settings
    _settings = new_settings


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
