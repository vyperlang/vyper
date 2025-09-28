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


VENOM_ENABLE_LEGACY_OPTIMIZER = False
if (_venom_elo := os.environ.get("VENOM_ENABLE_LEGACY_OPTIMIZER")) is not None:
    VENOM_ENABLE_LEGACY_OPTIMIZER = bool(int(_venom_elo))


# TODO: use StringEnum (requires refactoring vyper.utils to avoid import cycle)
class OptimizationLevel(Enum):
    NONE = 1
    GAS = 2
    CODESIZE = 3
    O0 = 4  # No optimizations
    O1 = 5  # Basic optimizations
    O2 = 6  # Standard "stable" optimizations (default)
    O3 = 7  # Aggressive optimizations -- experimental posibly unsafe
    Os = 8  # Optimize for size
    Oz = 9  # Extreme size optimization -- disregard performance completely

    @classmethod
    def from_string(cls, val):
        match val:
            case "none" | "O0":
                return cls.NONE
            case "gas" | "O2":
                return cls.GAS
            case "codesize" | "Os":
                return cls.CODESIZE
            case "O1":
                return cls.O1
            case "O3":
                return cls.O3
            case "Oz":
                return cls.Oz
        raise ValueError(f"unrecognized optimization level: {val}")

    @classmethod
    def default(cls):
        return cls.GAS

    def __str__(self):
        return self._name_ if self._name_.startswith("O") else self._name_.lower()


DEFAULT_ENABLE_DECIMALS = False


@dataclass
class VenomOptimizationFlags:
    enable_inlining: bool = True
    enable_cse: bool = True
    enable_sccp: bool = True
    enable_load_elimination: bool = True
    enable_dead_store_elimination: bool = True
    enable_algebraic_optimization: bool = True
    enable_branch_optimization: bool = True
    enable_mem2var: bool = True
    enable_simplify_cfg: bool = True
    enable_remove_unused_variables: bool = True
    inline_threshold: int = 15

    @classmethod
    def from_optimization_level(cls, level: OptimizationLevel):
        if level in (OptimizationLevel.NONE, OptimizationLevel.O0):
            return cls(
                enable_inlining=False,
                enable_cse=False,
                enable_sccp=False,
                enable_load_elimination=False,
                enable_dead_store_elimination=False,
                enable_algebraic_optimization=False,
                enable_branch_optimization=False,
                enable_mem2var=False,
                enable_simplify_cfg=False,
                enable_remove_unused_variables=False,
            )
        elif level == OptimizationLevel.O1:
            return cls(
                enable_inlining=False,
                enable_cse=False,
                enable_sccp=True,
                enable_load_elimination=False,
                enable_dead_store_elimination=True,
                enable_algebraic_optimization=True,
                enable_branch_optimization=False,
                enable_mem2var=False,
                enable_simplify_cfg=True,
                enable_remove_unused_variables=True,
            )
        elif level in (OptimizationLevel.GAS, OptimizationLevel.O2):
            return cls()
        elif level == OptimizationLevel.O3:
            return cls(inline_threshold=30)  # More aggressive inlining
        elif level in (OptimizationLevel.CODESIZE, OptimizationLevel.Os):
            return cls(inline_threshold=5)  # Less aggressive inlining for size
        elif level == OptimizationLevel.Oz:
            return cls(
                enable_inlining=False,  # temp, because inlining will probably decrease size in many cases
                inline_threshold=0,
            )
        else:
            return cls()

    def as_dict(self):
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(**data)


@dataclass
class Settings:
    compiler_version: Optional[str] = None
    optimize: Optional[OptimizationLevel] = None
    evm_version: Optional[str] = None
    experimental_codegen: Optional[bool] = None
    debug: Optional[bool] = None
    enable_decimals: Optional[bool] = None
    nonreentrancy_by_default: Optional[bool] = None
    venom_flags: Optional[VenomOptimizationFlags] = None

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
        if self.nonreentrancy_by_default is not None:
            assert isinstance(self.nonreentrancy_by_default, bool)
        if self.venom_flags is not None:
            assert isinstance(self.venom_flags, VenomOptimizationFlags)

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
            ret.append(" --venom-experimental")
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
        if "venom_flags" in ret and ret["venom_flags"] is not None:
            ret["venom_flags"] = ret["venom_flags"]
        return ret

    @classmethod
    def from_dict(cls, data):
        data = data.copy()
        if "optimize" in data:
            data["optimize"] = OptimizationLevel.from_string(data["optimize"])
        if "venom_flags" in data and data["venom_flags"] is not None:
            data["venom_flags"] = VenomOptimizationFlags.from_dict(data["venom_flags"])
        return cls(**data)


def should_run_legacy_optimizer(settings: Settings):
    if settings.optimize in (OptimizationLevel.NONE, OptimizationLevel.O0):
        return False
    if settings.experimental_codegen and not VENOM_ENABLE_LEGACY_OPTIMIZER:
        return False

    return True


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
    for field in dataclasses.fields(ret):
        if field.name == "compiler_version":
            continue
        if field.name == "venom_flags":
            val = getattr(one, field.name) or getattr(two, field.name)
        else:
            pretty_name = field.name.replace("_", "-")  # e.g. evm_version -> evm-version
            val = _merge_one(getattr(one, field.name), getattr(two, field.name), pretty_name)
        setattr(ret, field.name, val)

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
    return _settings.optimize in (OptimizationLevel.NONE, OptimizationLevel.O0)


def _is_debug_mode():
    return get_global_settings().debug
