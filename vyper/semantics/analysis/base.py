import enum
from typing import Any, Dict, List, Optional, Tuple, Union

from vyper import ast as vy_ast
from vyper.abi_types import ABIType
from vyper.exceptions import (
    CompilerPanic,
    ImmutableViolation,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    UnexpectedNodeType,
    UnexpectedValue,
    UnknownAttribute,
)
from vyper.semantics.namespace import validate_identifier
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.types.base import VyperType


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
    def options(cls) -> List["StringEnum"]:
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

                                    
# TODO: move me to locations.py?
class DataLocation(enum.Enum):
    UNSET = 0
    MEMORY = 1
    STORAGE = 2
    CALLDATA = 3
    CODE = 4


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


class VarInfo:
    """
    VarInfo are objects that represent the type of a variable,
    plus associated metadata like location and constancy attributes

    Class Attributes
    -----------------
    _id : str
        The name of the type.
    _is_callable : bool, optional
        If `True`, attempts to assign this value without calling it will raise
        a more expressive error message recommending that the user performs a
        function call.

    Object Attributes
    -----------------
    is_constant : bool, optional
        If `True`, this is a variable defined with the `constant()` modifier
    """

    _id: str

    def __init__(
        self,
        typ: VyperType,
        decl_node: Optional[vy_ast.VyperNode] = None,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
        is_local_var: bool = False,
    ) -> None:
        self.typ = typ
        self.location = location
        self.is_constant = is_constant
        self.is_public = is_public
        self.is_immutable = is_immutable
        self.is_local_var = is_local_var

        # TODO maybe we don't actually need this
        self.decl_node = decl_node

        self._modification_count = 0

    def set_position(self, position: DataPosition) -> None:
        if hasattr(self, "position"):
            raise CompilerPanic("Position was already assigned")
        if self.location != position._location:
            if self.location == DataLocation.UNSET:
                self.location = position._location
            else:
                raise CompilerPanic("Incompatible locations")
        self.position = position

    def validate_numeric_op(
        self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp, vy_ast.AugAssign]
    ) -> None:
        """
        Validate a numeric operation for this type.

        Arguments
        ---------
        node : UnaryOp | BinOp | AugAssign
            Vyper ast node of the numeric operation to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise InvalidOperation(f"Cannot perform {node.op.description} on {self}", node)

    def validate_boolean_op(self, node: vy_ast.BoolOp) -> None:
        """
        Validate a boolean operation for this type.

        Arguments
        ---------
        node : BoolOp
            Vyper ast node of the boolean operation to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise InvalidOperation(f"Invalid type for operand: {self}", node)

    def validate_comparator(self, node: vy_ast.Compare) -> None:
        """
        Validate a comparator for this type.

        Arguments
        ---------
        node : Compare
            Vyper ast node of the comparator to be validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        if not isinstance(node.op, (vy_ast.Eq, vy_ast.NotEq)):
            raise InvalidOperation(
                f"Cannot perform {node.op.description} comparison on {self}", node
            )

    def validate_implements(self, node: vy_ast.AnnAssign) -> None:
        """
        Validate an implements statement.

        This method is unique to user-defined interfaces. It should not be
        included in other types.

        Arguments
        ---------
        node : AnnAssign
            Vyper ast node of the implements statement being validated.

        Returns
        -------
        None. A failed validation must raise an exception.
        """
        raise StructureException("Value is not an interface", node)

    def infer_arg_types(self, node: vy_ast.Call) -> List[Optional["VyperType"]]:
        """
        Performs the necessary type inference and returns the call's arguments' types.

        This method must raise if the value is not callable, or the type for a call
        argument cannot be determined.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to perform type inference.

        Returns
        -------
        VyperType, optional
            List of types for the call's arguments.
        """
        raise StructureException("Value is not callable", node)

    def validate_index_type(self, node: vy_ast.Index) -> None:
        """
        Validate an index reference, e.g. x[1]. Raises if the index is invalid.

        Arguments
        ---------
        node : Index
            Vyper ast node from the `slice` member of a Subscript node.
        """
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def compare_signature(self, other: "VyperType") -> bool:
        """
        Compare the signature of this type with another type.

        Used when determining if an interface has been implemented. This method
        should not be directly implemented by any inherited classes.
        """

        if not self.is_public:
            return False

        arguments, return_type = self.getter_signature()
        other_arguments, other_return_type = other.getter_signature()

        if len(arguments) != len(other_arguments):
            return False
        for a, b in zip(arguments, other_arguments):
            if not a.compare_type(b):
                return False
        if return_type and not return_type.compare_type(other_return_type):  # type: ignore
            return False

        return True


class ExprInfo:
    """
    Class which represents the analysis associated with an expression
    """

    def __init__(self, typ, var_info = None):
        self.typ: VyperType = typ
        self.var_info: Optional[VarInfo] = var_info

        if var_info is not None and var_info.typ != self.typ:
            raise CompilerPanic("Bad analysis: non-matching types {var_info.typ} / {self.typ}")

    @classmethod
    def from_varinfo(cls, var_info: VarInfo):
        return cls(var_info.typ, var_info)

    def validate_modification(
        self, mutability: Any, node: vy_ast.VyperNode  # should be StateMutability, import cycle
    ) -> None:
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
        # TODO: break this cycle, probably by moving this to validation module
        from vyper.semantics.types.function import StateMutability

        if mutability <= StateMutability.VIEW and self.location == DataLocation.STORAGE:
            raise StateAccessViolation(
                f"Cannot modify storage in a {mutability.value} function", node
            )

        if self.location == DataLocation.CALLDATA:
            raise ImmutableViolation("Cannot write to calldata", node)
        if self.is_constant:
            raise ImmutableViolation("Constant value cannot be written to", node)
        if self.is_immutable:
            if node.get_ancestor(vy_ast.FunctionDef).get("name") != "__init__":
                raise ImmutableViolation("Immutable value cannot be written to", node)
            if self._modification_count:
                raise ImmutableViolation(
                    "Immutable value cannot be modified after assignment", node
                )
            self._modification_count += 1

        if isinstance(node, vy_ast.AugAssign):
            self.var_info.typ.validate_numeric_op(node)


class KwargSettings:
    # convenience class which holds metadata about how to process kwargs.
    # contains the `default` value for the kwarg as a python value, and a
    # flag `require_literal`, which, when True, indicates that the kwarg
    # must be set to a compile-time constant at any call site.
    # (note that the kwarg processing machinery will return a
    # Python value instead of an AST or IRnode in this case).
    def __init__(self, typ, default, require_literal=False):
        self.typ = typ
        self.default = default
        self.require_literal = require_literal


# A type type. Only used internally for builtins
class TYPE_T:
    def __init__(self, typedef):
        self.typedef = typedef

    def __repr__(self):
        return f"type({self.typedef})"
