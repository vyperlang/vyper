import enum
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, Optional, Union

from vyper import ast as vy_ast
from vyper.compiler.input_bundle import InputBundle
from vyper.exceptions import CompilerPanic, StructureException
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import VyperType
from vyper.utils import StringEnum

if TYPE_CHECKING:
    from vyper.semantics.types.module import InterfaceT, ModuleT


class FunctionVisibility(StringEnum):
    EXTERNAL = enum.auto()
    INTERNAL = enum.auto()
    DEPLOY = enum.auto()


class StateMutability(StringEnum):
    PURE = enum.auto()
    VIEW = enum.auto()
    NONPAYABLE = enum.auto()
    PAYABLE = enum.auto()

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
class Modifiability(StringEnum):
    # compile-time / always constant
    CONSTANT = enum.auto()

    # things that are constant within the current message call, including
    # block.*, msg.*, tx.* and immutables
    RUNTIME_CONSTANT = enum.auto()

    # could potentially add more fine-grained here as needed, like
    # CONSTANT_AFTER_DEPLOY, TX_CONSTANT, BLOCK_CONSTANT, etc.

    # is writeable/can result in arbitrary state or memory changes
    MODIFIABLE = enum.auto()

    @classmethod
    def from_state_mutability(cls, mutability: StateMutability):
        if mutability == StateMutability.PURE:
            return cls.CONSTANT
        if mutability == StateMutability.VIEW:
            return cls.RUNTIME_CONSTANT
        # sanity check in case more StateMutability levels are added in the future
        assert mutability in (StateMutability.PAYABLE, StateMutability.NONPAYABLE)
        return cls.MODIFIABLE


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


class ModuleOwnership(StringEnum):
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
                f"ownership already set to `{self.ownership}`", node, self.ownership_decl
            )
        self.ownership = module_ownership

    def __hash__(self):
        return hash(id(self.module_t))


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
    module_info: ModuleInfo
    dependencies: list[ModuleInfo]
    node: Optional[vy_ast.VyperNode] = None


# analysis result of UsesDecl
@dataclass
class UsesInfo(AnalysisResult):
    used_modules: list[ModuleInfo]
    node: Optional[vy_ast.VyperNode] = None


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

    def is_module_variable(self):
        return self.location not in (DataLocation.UNSET, DataLocation.MEMORY)

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

    # the chain of attribute parents for this expr
    attribute_chain: list["ExprInfo"] = field(default_factory=list)

    def __post_init__(self):
        should_match = ("typ", "location", "modifiability")
        if self.var_info is not None:
            for attr in should_match:
                if getattr(self.var_info, attr) != getattr(self, attr):
                    raise CompilerPanic("Bad analysis: non-matching {attr}: {self}")

        self._writes = []
        self._reads = []

    def get_root_moduleinfo(self) -> Optional[ModuleInfo]:
        chain = self.attribute_chain
        if len(chain) == 0:
            return None
        return chain[0].module_info

    # find an exprinfo in the attribute chain which has a varinfo
    # e.x. `x` will return exprinfo for `x`
    # `module.foo` will return exprinfo for `module.foo`
    def get_root_varinfo(self) -> Optional[VarInfo]:
        for expr_info in self.attribute_chain + [self]:
            if expr_info.var_info is not None:
                return expr_info.var_info
        return None

    @classmethod
    def from_varinfo(cls, var_info: VarInfo, attribute_chain=None) -> "ExprInfo":
        return cls(
            var_info.typ,
            var_info=var_info,
            location=var_info.location,
            modifiability=var_info.modifiability,
            attribute_chain=attribute_chain or [],
        )

    @classmethod
    def from_moduleinfo(cls, module_info: ModuleInfo, attribute_chain=None) -> "ExprInfo":
        modifiability = Modifiability.RUNTIME_CONSTANT
        if module_info.ownership >= ModuleOwnership.USES:
            modifiability = Modifiability.MODIFIABLE

        return cls(
            module_info.module_t,
            module_info=module_info,
            modifiability=modifiability,
            attribute_chain=attribute_chain or [],
        )

    def copy_with_type(self, typ: VyperType, attribute_chain=None) -> "ExprInfo":
        """
        Return a copy of the ExprInfo but with the type set to something else
        """
        to_copy = ("location", "modifiability")
        fields = {k: getattr(self, k) for k in to_copy}
        if attribute_chain is not None:
            fields["attribute_chain"] = attribute_chain
        return self.__class__(typ=typ, **fields)
