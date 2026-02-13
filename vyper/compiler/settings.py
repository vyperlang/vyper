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
    # TODO: O1 (minimal passes) is currently disabled because it can cause
    # "stack too deep" errors. Re-enable once stack spilling machinery is
    # implemented to allow compilation with minimal optimization passes.
    O2 = 6  # Standard "stable" optimizations (default)
    O3 = 7  # Aggressive optimizations -- experimental possibly unsafe
    Os = 8  # Optimize for size

    @classmethod
    def from_string(cls, val):
        match val:
            case "none":
                return cls.NONE
            # O1 maps to O2 for now until stack spilling is implemented
            case "O1" | "O2" | "gas":
                return cls.GAS
            case "codesize" | "Os":
                return cls.CODESIZE
            case "O3" | "o3":
                return cls.O3
        raise ValueError(f"unrecognized optimization level: {val}")

    @classmethod
    def default(cls):
        return cls.GAS

    def __str__(self):
        return self._name_ if self._name_.startswith("O") else self._name_.lower()


DEFAULT_ENABLE_DECIMALS = False

# Inlining threshold constants
INLINE_THRESHOLD_SIZE = 5  # Conservative for size optimization
INLINE_THRESHOLD_DEFAULT = 15  # Standard inlining
INLINE_THRESHOLD_AGGRESSIVE = 30  # Aggressive inlining for O3


@dataclass
class VenomOptimizationFlags:
    level: OptimizationLevel = OptimizationLevel.default()

    # Disable flags - default False means optimization is enabled
    # These are used to override the defaults for the optimization level
    disable_inlining: bool = False
    disable_cse: bool = False
    disable_sccp: bool = False
    disable_load_elimination: bool = False
    disable_dead_store_elimination: bool = False
    disable_algebraic_optimization: bool = False
    disable_branch_optimization: bool = False
    disable_assert_elimination: bool = False
    disable_mem2var: bool = False
    disable_simplify_cfg: bool = False
    disable_remove_unused_variables: bool = False

    # Tuning parameters
    inline_threshold: Optional[int] = None

    def __post_init__(self):
        # Set default optimization level if not provided
        if self.level is None:
            self.level = OptimizationLevel.default()

        # Always set inline_threshold based on level
        if self.inline_threshold is None:
            self.inline_threshold = self._get_inline_threshold_for_level(self.level)

    def _get_inline_threshold_for_level(self, level: OptimizationLevel) -> int:
        if level == OptimizationLevel.O3:
            return INLINE_THRESHOLD_AGGRESSIVE
        elif level in (OptimizationLevel.Os, OptimizationLevel.CODESIZE):
            return INLINE_THRESHOLD_SIZE
        elif level == OptimizationLevel.NONE:
            return INLINE_THRESHOLD_DEFAULT
        else:
            return INLINE_THRESHOLD_DEFAULT

    def _update_inline_threshold(self):
        self.inline_threshold = self._get_inline_threshold_for_level(self.level)

    def set_level(self, level: OptimizationLevel):
        """Set optimization level and update dependent parameters."""
        self.level = level
        self._update_inline_threshold()

    def as_dict(self):
        ret = dataclasses.asdict(self)
        # Convert OptimizationLevel to string for JSON serialization
        if ret.get("level") is not None:
            ret["level"] = str(ret["level"])
        return ret

    @classmethod
    def from_dict(cls, data):
        data = data.copy()
        # Convert string back to OptimizationLevel
        if "level" in data and data["level"] is not None:
            data["level"] = OptimizationLevel.from_string(data["level"])
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

    def get_venom_flags(self) -> VenomOptimizationFlags:
        if self.venom_flags is None:
            assert self.optimize is not None  # help mypy
            return VenomOptimizationFlags(level=self.optimize)
        return self.venom_flags

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
        ret = {}
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            if field.name == "compiler_version":
                # compiler_version is not a compiler input, it can only come from
                # source code pragma.
                continue
            if field.name == "optimize":
                ret["optimize"] = str(value)
            elif field.name == "venom_flags":
                ret["venom_flags"] = value.as_dict()
            else:
                ret[field.name] = value
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
    if settings.optimize == OptimizationLevel.NONE:
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

    # Collect all values first before creating Settings to avoid double initialization
    values = {}
    for field in dataclasses.fields(Settings):
        if field.name == "compiler_version":
            continue
        if field.name != "venom_flags":
            pretty_name = field.name.replace("_", "-")  # e.g. evm_version -> evm-version
            val = _merge_one(getattr(one, field.name), getattr(two, field.name), pretty_name)
            if val is not None:
                values[field.name] = val

    # Now handle venom_flags based on the merged optimize value
    # If either source has explicit venom_flags with customizations, use it
    # Otherwise let Settings.__post_init__ create the default based on optimize
    venom_one = getattr(one, "venom_flags", None)
    venom_two = getattr(two, "venom_flags", None)

    # Pick the venom_flags that matches the merged optimize level, if any
    merged_optimize = values.get("optimize")
    if venom_two and venom_two.level == merged_optimize:
        values["venom_flags"] = venom_two
    elif venom_one and venom_one.level == merged_optimize:
        values["venom_flags"] = venom_one
    # Otherwise don't set it - let __post_init__ create the right one

    return Settings(**values)


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
    return _settings.optimize == OptimizationLevel.GAS or _settings.optimize == OptimizationLevel.O3


def _opt_none():
    return _settings.optimize == OptimizationLevel.NONE


def _is_debug_mode():
    return get_global_settings().debug
