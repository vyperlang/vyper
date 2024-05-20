import enum
from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Optional, Union

from vyper import ast as vy_ast
from vyper.compiler.input_bundle import CompilerInput
from vyper.exceptions import CompilerPanic, StructureException
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.primitives import SelfT
from vyper.utils import OrderedSet, StringEnum

if TYPE_CHECKING:
    from vyper.semantics.types.function import ContractFunctionT
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


@dataclass
class VarOffset:
    position: int


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


@dataclass(frozen=True)
class ImportInfo(AnalysisResult):
    typ: Union[ModuleInfo, "InterfaceT"]
    alias: str  # the name in the namespace
    qualified_module_name: str  # for error messages
    compiler_input: CompilerInput  # to recover file info for ast export
    node: vy_ast.VyperNode

    def to_dict(self):
        ret = {"alias": self.alias, "qualified_module_name": self.qualified_module_name}

        ret["source_id"] = self.compiler_input.source_id
        ret["path"] = str(self.compiler_input.path)
        ret["resolved_path"] = str(self.compiler_input.resolved_path)
        ret["file_sha256sum"] = self.compiler_input.sha256sum

        return ret


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


# analysis result of ExportsDecl
@dataclass
class ExportsInfo(AnalysisResult):
    functions: list["ContractFunctionT"]
    used_modules: OrderedSet[ModuleInfo]


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
    decl_node: Optional[vy_ast.VariableDecl] = None

    def __hash__(self):
        return hash(id(self))

    def __post_init__(self):
        self.position = None
        self._modification_count = 0

    @property
    def getter_ast(self) -> Optional[vy_ast.VyperNode]:
        assert self.decl_node is not None  # help mypy
        ret = self.decl_node._expanded_getter
        assert (ret is not None) == self.is_public, self
        return ret

    def set_position(self, position: VarOffset) -> None:
        if self.position is not None:
            raise CompilerPanic(f"Position was already assigned: {self}")
        assert isinstance(position, VarOffset)  # sanity check
        self.position = position

    def is_state_variable(self):
        non_state_locations = (DataLocation.UNSET, DataLocation.MEMORY, DataLocation.CALLDATA)
        # `self` gets a VarInfo, but it is not considered a state
        # variable (it is magic), so we ignore it here.
        return self.location not in non_state_locations and not isinstance(self.typ, SelfT)

    def get_size(self) -> int:
        return self.typ.get_size_in(self.location)

    @property
    def is_storage(self):
        return self.location == DataLocation.STORAGE

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


@dataclass(frozen=True)
class VarAccess:
    variable: VarInfo
    path: tuple[str | object, ...]

    # A sentinel indicating a subscript access
    SUBSCRIPT_ACCESS: ClassVar[Any] = object()

    @cached_property
    def attrs(self):
        ret = []
        for s in self.path:
            if s is self.SUBSCRIPT_ACCESS:
                break
            ret.append(s)
        return tuple(ret)

    def contains(self, other):
        # VarAccess("v", ("a")) `contains` VarAccess("v", ("a", "b", "c"))
        sub_attrs = other.attrs[: len(self.attrs)]
        return self.variable == other.variable and sub_attrs == self.attrs

    def to_dict(self):
        var = self.variable
        if var.decl_node is None:
            # happens for builtins or `self` accesses
            return None

        # map SUBSCRIPT_ACCESS to `"$subscript_access"` (which is an identifier
        # which can't be constructed by the user)
        path = ["$subscript_access" if s is self.SUBSCRIPT_ACCESS else s for s in self.path]
        varname = var.decl_node.target.id

        decl_node = var.decl_node.get_id_dict()
        ret = {"name": varname, "decl_node": decl_node, "access_path": path}
        return ret


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
    attr: Optional[str] = None

    def __post_init__(self):
        should_match = ("typ", "location", "modifiability")
        if self.var_info is not None:
            for attr in should_match:
                if getattr(self.var_info, attr) != getattr(self, attr):
                    raise CompilerPanic(f"Bad analysis: non-matching {attr}: {self}")

        self._writes: OrderedSet[VarAccess] = OrderedSet()
        self._reads: OrderedSet[VarAccess] = OrderedSet()

    @classmethod
    def from_varinfo(cls, var_info: VarInfo, **kwargs) -> "ExprInfo":
        return cls(
            var_info.typ,
            var_info=var_info,
            location=var_info.location,
            modifiability=var_info.modifiability,
            **kwargs,
        )

    @classmethod
    def from_moduleinfo(cls, module_info: ModuleInfo, **kwargs) -> "ExprInfo":
        modifiability = Modifiability.RUNTIME_CONSTANT
        if module_info.ownership >= ModuleOwnership.USES:
            modifiability = Modifiability.MODIFIABLE

        return cls(
            module_info.module_t, module_info=module_info, modifiability=modifiability, **kwargs
        )

    def copy_with_type(self, typ: VyperType, **kwargs) -> "ExprInfo":
        """
        Return a copy of the ExprInfo but with the type set to something else
        """
        to_copy = ("location", "modifiability")
        fields = {k: getattr(self, k) for k in to_copy}
        for t in to_copy:
            assert t not in kwargs
        return self.__class__(typ=typ, **fields, **kwargs)
