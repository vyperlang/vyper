import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from vyper import ast as vy_ast
from vyper.compiler.input_bundle import InputBundle
from vyper.exceptions import (
    CompilerPanic,
    ImmutableViolation,
    StateAccessViolation,
    StructureException,
    VyperInternalException,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import VyperType

if TYPE_CHECKING:
    from vyper.semantics.types.module import InterfaceT, ModuleT


class _StringEnum(enum.Enum):
    @staticmethod
    def auto():
        return enum.auto()

    # Must be first, or else won't work, specifies what .value is
    def _generate_next_value_(name, start, count, last_values):
        return name.lower()

    # Override ValueError with our own internal exception
    @classmethod
    def _missing_(cls, value):
        raise VyperInternalException(f"{value} is not a valid {cls.__name__}")

    @classmethod
    def is_valid_value(cls, value: str) -> bool:
        return value in set(o.value for o in cls)

    @classmethod
    def options(cls) -> List["_StringEnum"]:
        return list(cls)

    @classmethod
    def values(cls) -> List[str]:
        return [v.value for v in cls.options()]

    # Comparison operations
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise CompilerPanic("bad comparison")
        return self is other

    # Python normally does __ne__(other) ==> not self.__eq__(other)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise CompilerPanic("bad comparison")
        options = self.__class__.options()
        return options.index(self) < options.index(other)  # type: ignore

    def __le__(self, other: object) -> bool:
        return self.__eq__(other) or self.__lt__(other)

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return self.__eq__(other) or self.__gt__(other)


class FunctionVisibility(_StringEnum):
    EXTERNAL = enum.auto()
    INTERNAL = enum.auto()
    CONSTRUCTOR = enum.auto()

    @classmethod
    def is_valid_value(cls, value: str) -> bool:
        # make CONSTRUCTOR visibility not available to the user
        # (although as a design note - maybe `@constructor` should
        # indeed be available)
        return super().is_valid_value(value) and value != "constructor"


class StateMutability(_StringEnum):
    # TODO: these can just be enum.auto() right?
    PURE = _StringEnum.auto()
    VIEW = _StringEnum.auto()
    NONPAYABLE = _StringEnum.auto()
    PAYABLE = _StringEnum.auto()

    @classmethod
    def from_abi(cls, abi_dict: Dict) -> "StateMutability":
        """
        Extract stateMutability from an entry in a contract's ABI
        """
        if "stateMutability" in abi_dict:
            return cls(abi_dict["stateMutability"])
        elif abi_dict.get("payable"):
            return StateMutability.PAYABLE
        elif "constant" in abi_dict and abi_dict["constant"]:
            return StateMutability.VIEW
        else:  # Assume nonpayable if neither field is there, or constant/payable not set
            return StateMutability.NONPAYABLE
        # NOTE: The state mutability nonpayable is reflected in Solidity by not
        #       specifying a state mutability modifier at all. Do the same here.


# classify the constancy of an expression
# CMC 2023-12-31 note that we now have three ways of classifying mutability in
# the codebase: StateMutability (for functions), Modifiability (for expressions
# and variables) and Constancy (in codegen). context.Constancy can/should
# probably be refactored away though as those kinds of checks should be done
# during analysis.
class Modifiability(enum.IntEnum):
    # is writeable/can result in arbitrary state or memory changes
    MODIFIABLE = enum.auto()

    # could potentially add more fine-grained here as needed, like
    # CONSTANT_AFTER_DEPLOY, TX_CONSTANT, BLOCK_CONSTANT, etc.

    # things that are constant within the current message call, including
    # block.*, msg.*, tx.* and immutables
    RUNTIME_CONSTANT = enum.auto()

    # compile-time / always constant
    CONSTANT = enum.auto()


class DataPosition:
    _location: DataLocation


class CalldataOffset(DataPosition):
    __slots__ = ("dynamic_offset", "static_offset")
    _location = DataLocation.CALLDATA

    def __init__(self, static_offset, dynamic_offset=None):
        self.static_offset = static_offset
        self.dynamic_offset = dynamic_offset

    def __repr__(self):
        if self.dynamic_offset is not None:
            return f"<CalldataOffset: static {self.static_offset}, dynamic {self.dynamic_offset})>"
        else:
            return f"<CalldataOffset: static {self.static_offset}, no dynamic>"


class MemoryOffset(DataPosition):
    __slots__ = ("offset",)
    _location = DataLocation.MEMORY

    def __init__(self, offset):
        self.offset = offset

    def __repr__(self):
        return f"<MemoryOffset: {self.offset}>"


class StorageSlot(DataPosition):
    __slots__ = ("position",)
    _location = DataLocation.STORAGE

    def __init__(self, position):
        self.position = position

    def __repr__(self):
        return f"<StorageSlot: {self.position}>"


class CodeOffset(DataPosition):
    __slots__ = ("offset",)
    _location = DataLocation.CODE

    def __init__(self, offset):
        self.offset = offset

    def __repr__(self):
        return f"<CodeOffset: {self.offset}>"


class ModuleOwnership(enum.IntEnum):
    NO_OWNERSHIP = enum.auto()  # readable
    USES = enum.auto()  # writeable
    INITIALIZES = enum.auto()  # initializes


# base class for things that are the "result" of analysis
class AnalysisResult:
    pass


@dataclass
class ModuleInfo(AnalysisResult):
    module_t: "ModuleT"
    alias: str
    ownership: ModuleOwnership = ModuleOwnership.NO_OWNERSHIP
    ownership_decl: Optional[vy_ast.VyperNode] = None

    @property
    def module_node(self):
        return self.module_t._module

    # duck type, conform to interface of VarInfo and ExprInfo
    @property
    def typ(self):
        return self.module_t

    def set_ownership(self, module_ownership: ModuleOwnership, node: Optional[vy_ast.VyperNode]):
        if self.ownership != ModuleOwnership.NO_OWNERSHIP:
            raise StructureException(
                f"ownership already set to {self.module_ownership}", node, self.ownership_decl
            )
        self.ownership = module_ownership


@dataclass
class ImportInfo(AnalysisResult):
    typ: Union[ModuleInfo, "InterfaceT"]
    alias: str  # the name in the namespace
    qualified_module_name: str  # for error messages
    # source_id: int
    input_bundle: InputBundle
    node: vy_ast.VyperNode


# analysis result of InitializesDecl
@dataclass
class InitializesInfo(AnalysisResult):
    module_t: "ModuleT"
    dependencies: list["ModuleT"]


# analysis result of UsesDecl
@dataclass
class UsesInfo(AnalysisResult):
    used_modules: list["ModuleT"]


@dataclass
class VarInfo:
    """
    VarInfo are objects that represent the type of a variable,
    plus associated metadata like location and modifiability attributes

    Object Attributes
    -----------------
    location: DataLocation of this variable
    modifiability: Modifiability of this variable
    """

    typ: VyperType
    location: DataLocation = DataLocation.UNSET
    modifiability: Modifiability = Modifiability.MODIFIABLE
    is_public: bool = False
    decl_node: Optional[vy_ast.VyperNode] = None

    def __hash__(self):
        return hash(id(self))

    def __post_init__(self):
        self._modification_count = 0

    def set_position(self, position: DataPosition) -> None:
        if hasattr(self, "position"):
            raise CompilerPanic("Position was already assigned")
        if self.location != position._location:
            if self.location == DataLocation.UNSET:
                self.location = position._location
            elif self.is_transient and position._location == DataLocation.STORAGE:
                # CMC 2023-12-31 - use same allocator for storage and transient
                # for now, this should be refactored soon.
                pass
            else:
                raise CompilerPanic("Incompatible locations")
        self.position = position

    @property
    def is_transient(self):
        return self.location == DataLocation.TRANSIENT

    @property
    def is_immutable(self):
        return self.location == DataLocation.CODE

    @property
    def is_constant(self):
        res = self.location == DataLocation.UNSET
        assert res == (self.modifiability == Modifiability.CONSTANT)
        return res


@dataclass
class ExprInfo:
    """
    Class which represents the analysis associated with an expression
    """

    typ: VyperType
    var_info: Optional[VarInfo] = None
    module_info: Optional[ModuleInfo] = None
    location: DataLocation = DataLocation.UNSET
    modifiability: Modifiability = Modifiability.MODIFIABLE

    def __post_init__(self):
        should_match = ("typ", "location", "modifiability")
        if self.var_info is not None:
            for attr in should_match:
                if getattr(self.var_info, attr) != getattr(self, attr):
                    raise CompilerPanic("Bad analysis: non-matching {attr}: {self}")

    @classmethod
    def from_varinfo(cls, var_info: VarInfo) -> "ExprInfo":
        return cls(
            var_info.typ,
            var_info=var_info,
            location=var_info.location,
            modifiability=var_info.modifiability,
        )

    @classmethod
    def from_moduleinfo(cls, module_info: ModuleInfo) -> "ExprInfo":
        modifiability = Modifiability.MODIFIABLE
        if module_info.ownership < ModuleOwnership.USES:
            modifiability = Modifiability.CONSTANT

        return cls(module_info.module_t, module_info=module_info, modifiability=modifiability)

    def copy_with_type(self, typ: VyperType) -> "ExprInfo":
        """
        Return a copy of the ExprInfo but with the type set to something else
        """
        to_copy = ("location", "modifiability")
        fields = {k: getattr(self, k) for k in to_copy}
        return self.__class__(typ=typ, **fields)

    def validate_modification(self, node: vy_ast.VyperNode, mutability: StateMutability) -> None:
        """
        Validate an attempt to modify this value.

        Raises if the value is a constant or involves an invalid operation.

        Arguments
        ---------
        node : Assign | AugAssign | Call
            Vyper ast node of the modifying action.
        mutability: StateMutability
            The mutability of the context (e.g., pure function) we are currently in
        """
        if mutability <= StateMutability.VIEW and self.location == DataLocation.STORAGE:
            raise StateAccessViolation(
                f"Cannot modify storage in a {mutability.value} function", node
            )

        if self.location == DataLocation.CALLDATA:
            raise ImmutableViolation("Cannot write to calldata", node)

        if self.modifiability == Modifiability.RUNTIME_CONSTANT:
            if self.location == DataLocation.CODE:
                if node.get_ancestor(vy_ast.FunctionDef).get("name") != "__init__":
                    raise ImmutableViolation("Immutable value cannot be written to", node)

                # special handling for immutable variables in the ctor
                # TODO: we probably want to remove this restriction.
                if self.var_info._modification_count:  # type: ignore
                    raise ImmutableViolation(
                        "Immutable value cannot be modified after assignment", node
                    )
                self.var_info._modification_count += 1  # type: ignore
            else:
                raise ImmutableViolation("Environment variable cannot be written to", node)

        if self.modifiability == Modifiability.CONSTANT:
            msg = "Constant value cannot be written to."
            if self.module_info is not None:
                msg += f"\n(hint: add `uses: {self.module_info.alias}` as "
                msg += "a top-level statement to your contract)."
            raise ImmutableViolation(msg, node)

        if isinstance(node, vy_ast.AugAssign):
            self.typ.validate_numeric_op(node)
