import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Union

from vyper import ast as vy_ast
from vyper.compiler.input_bundle import InputBundle
from vyper.exceptions import (
    CompilerPanic,
    ImmutableViolation,
    StateAccessViolation,
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
            raise CompilerPanic("Can only compare like types.")
        return self is other

    # Python normally does __ne__(other) ==> not self.__eq__(other)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, self.__class__):
            raise CompilerPanic("Can only compare like types.")
        options = self.__class__.options()
        return options.index(self) < options.index(other)  # type: ignore

    def __le__(self, other: object) -> bool:
        return self.__eq__(other) or self.__lt__(other)

    def __gt__(self, other: object) -> bool:
        return not self.__le__(other)

    def __ge__(self, other: object) -> bool:
        return self.__eq__(other) or self.__gt__(other)


class FunctionVisibility(_StringEnum):
    # TODO: these can just be enum.auto() right?
    EXTERNAL = _StringEnum.auto()
    INTERNAL = _StringEnum.auto()


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


# base class for things that are the "result" of analysis
class AnalysisResult:
    pass


@dataclass
class ImportInfo(AnalysisResult):
    typ: Union["ModuleT", "InterfaceT"]
    alias: str  # the name in the namespace
    qualified_module_name: str  # for error messages
    # source_id: int
    input_bundle: InputBundle
    node: vy_ast.VyperNode

    def __eq__(self, other):
        return self is other


@dataclass
class VarInfo:
    """
    VarInfo are objects that represent the type of a variable,
    plus associated metadata like location and constancy attributes

    Object Attributes
    -----------------
    is_constant : bool, optional
        If `True`, this is a variable defined with the `constant()` modifier
    """

    typ: VyperType
    location: DataLocation = DataLocation.UNSET
    is_constant: bool = False
    is_public: bool = False
    is_immutable: bool = False
    is_transient: bool = False
    is_local_var: bool = False
    decl_node: Optional[vy_ast.VyperNode] = None

    def __hash__(self):
        return hash(id(self))

    def __post_init__(self):
        self._reads = []
        self._writes = []
        self.position = None  # the location provided by the allocator

    def set_position(self, position: DataPosition) -> None:
        if self.position is not None:
            raise CompilerPanic("Position was already assigned")
        if self.location != position._location:
            raise CompilerPanic(f"Incompatible locations: {self.location}, {position._location}")
        self.position = position


@dataclass
class ExprInfo:
    """
    Class which represents the analysis associated with an expression
    """

    typ: VyperType
    location: DataLocation = DataLocation.UNSET
    is_constant: bool = False
    is_immutable: bool = False
    _var_info: Optional[VarInfo] = None

    def __post_init__(self):
        should_match = ("typ", "location", "is_constant", "is_immutable")
        if self._var_info is not None:
            for attr in should_match:
                if getattr(self._var_info, attr) != getattr(self, attr):
                    raise CompilerPanic("Bad analysis: non-matching {attr}: {self}")

    @classmethod
    def from_varinfo(cls, var_info: VarInfo) -> "ExprInfo":
        return cls(
            var_info.typ,
            location=var_info.location,
            is_constant=var_info.is_constant,
            is_immutable=var_info.is_immutable,
            _var_info=var_info,
        )

    def copy_with_type(self, typ: VyperType) -> "ExprInfo":
        """
        Return a copy of the ExprInfo but with the type set to something else
        """
        to_copy = ("location", "is_constant", "is_immutable")
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
        if self.is_constant:
            raise ImmutableViolation("Constant value cannot be written to", node)

        func_node = node.get_ancestor(vy_ast.FunctionDef)
        func_t = func_node._metadata["func_type"]

        assert isinstance(func_node, vy_ast.FunctionDef)  # mypy hint
        assert self._var_info is not None  # mypy hint

        if self.is_immutable:
            if func_node.name != "__init__":
                raise ImmutableViolation("Immutable value cannot be written to", node)

            if len(self._var_info._writes) > 0:
                raise ImmutableViolation(
                    "Immutable value cannot be modified after assignment", node
                )

        # tag it in the metadata
        node._metadata["variable_write"] = self._var_info
        self._var_info._writes.append(node)
        func_t._variable_writes.append(node)

        if isinstance(node, vy_ast.AugAssign):
            self.typ.validate_numeric_op(node)
