import copy
from collections import OrderedDict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type, Union

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
from vyper.semantics.validation.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.namespace import validate_identifier


# TODO: move me to locations.py
class DataLocation(Enum):
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


# Some fake type with an overridden `compare_type` which accepts any RHS
# type of type `type_`
class _GenericTypeAcceptor:
    def __init__(self, type_):
        self.type_ = type_

    def compare_type(self, other):
        return isinstance(other, self.type_)


class VyperType:
    """
    Base class for vyper types.

    Attributes
    ----------
    _id : str
        The name of the type.
    _as_array: bool, optional
        If `True`, this type can be used as the base member for an array.
    _valid_literal : Tuple
        A tuple of Vyper ast classes that may be assigned this type.
    """

    _id: str
    _valid_literal: Tuple

    def __init__(self, members=None, *args, **kwargs) -> None:
        self.members = {}

        if hasattr(self, "_type_members"):
            for k, v in self._type_members.items():
                # for builtin members like `contract.address` -- skip namespace
                # validation, as it introduces a dependency cycle
                self.add_member(k, v, skip_namespace_validation=True)

        members = members or {}
        for k, v in members.items():
            self.add_member(k, v)

    @property
    def getter_signature(self):
        return (), self


    # TODO not sure if this is a great idea.
    @classmethod
    def any(cls):
        return _GenericTypeAcceptor(cls)


    @property
    def abi_type(self) -> ABIType:
        """
        The ABI type corresponding to this type
        """
        raise CompilerPanic("Method must be implemented by the inherited class")

    @property
    def canonical_abi_type(self) -> str:
        """
        The canonical name of this type. Used for ABI types and generating function signatures.
        """
        return self.abi_type.selector_name()

    def to_abi_dict(self, name: str = "") -> Dict[str, Any]:
        """
        The JSON ABI description of this type. Note for complex types,
        the implementation is overriden to be compliant with the spec:
        https://docs.soliditylang.org/en/v0.8.14/abi-spec.html#json
        > An object with members name, type and potentially components
          describes a typed variable. The canonical type is determined
          until a tuple type is reached and the string description up to
          that point is stored in type prefix with the word tuple, i.e.
          it will be tuple followed by a sequence of [] and [k] with
          integers k. The components of the tuple are then stored in the
          member components, which is of array type and has the same
          structure as the top-level object except that indexed is not
          allowed there.
        """
        return {"name": name, "type": self.canonical_abi_type}


    def validate_literal(self, node: vy_ast.Constant) -> None:
        """
        Validate whether a given literal can be annotated with this type.

        Arguments
        ---------
        node : VyperNode
            `Constant` Vyper ast node, or a list or tuple of constants.
        """
        if not isinstance(node, vy_ast.Constant):
            raise UnexpectedNodeType(f"Not a literal.", node)
        if not isinstance(node, self._valid_literal):
            raise InvalidLiteral(f"Invalid literal type for {cls.__name__}", node)

    @classmethod
    def compare_type(cls, other: "VyperType") -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by methods in `vyper.context.validation.utils`

        Arguments
        ---------
        other: VyperType
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, cls)

    @classmethod
    def fetch_call_return(self, node: vy_ast.Call) -> "BaseTypeDefinition":
        """
        Validate a call to this type and return the result.

        This method must raise if the type is not callable, or the call arguments
        are not valid.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to validate.

        Returns
        -------
        BaseTypeDefinition, optional
            Type generated as a result of the call.
        """
        raise StructureException("Type is not callable", node)

    @classmethod
    def get_subscripted_type(self, node: vy_ast.Index) -> None:
        """
        Return the type of a subscript expression, e.g. x[1]

        Arguments
        ---------
        node: Index
            Vyper ast node from the `slice` member of a Subscript node

        Returns
        -------
        BaseTypeDefinition
            Type object for value at the given index.
        """
        raise StructureException(f"'{self}' cannot be indexed into", node)

    def add_member(self, name: str, type_: "VyperType", skip_namespace_validation: bool = False) -> None:
        # skip_namespace_validation provides a way of bypassing validate_identifier, which
        # introduces a dependency cycle with the builtin_functions module
        if not skip_namespace_validation:
            validate_identifier(name)
        if name in self.members:
            raise NamespaceCollision(f"Member '{name}' already exists in {self}")
        self.members[name] = type_

    def get_member(self, key: str, node: vy_ast.VyperNode) -> "VyperType":
        if key in self.members:
            return self.members[key]

        # special error message for types with no members
        if not self.members:
            raise StructureException(f"{self} does not have members", node)

        suggestions_str = get_levenshtein_error_suggestions(key, self.members, 0.3)
        raise UnknownAttribute(f"{self} has no member '{key}'. {suggestions_str}", node)

    def __repr__(self):
        return self._id


    @classmethod
    def get_member(cls, key: str, node: vy_ast.Attribute) -> None:
        raise StructureException(f"{cls} does not have members", node)

    # TODO probably dead code
    @classmethod
    def validate_modification( cls, mutability: Any, node: vy_ast.VyperNode) -> None:
        # always raises - do not implement in inherited classes
        raise InvalidOperation("Cannot assign to a type", node)


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
    ) -> None:
        self.typ = vyper_type
        self.location = location
        self.is_constant = is_constant
        self.is_public = is_public
        self.is_immutable = is_immutable
        self.is_local_var = is_local_var

        # TODO maybe we don't actually need this
        self.decl_node = decl_node

        self._modification_count = 0

    # TODO move to VarInfo
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

    def fetch_call_return(self, node: vy_ast.Call) -> Union["BaseTypeDefinition", None]:
        """
        Validate a call to this value and return the result.

        This method must raise if the value is not callable, or the call arguments
        are not valid.

        Arguments
        ---------
        node : Call
            Vyper ast node of call action to validate.

        Returns
        -------
        BaseTypeDefinition, optional
            Type generated as a result of the call.
        """
        raise StructureException("Value is not callable", node)

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

    # TODO
    def compare_signature(self, other: "BaseTypeDefinition") -> bool:
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


class ExprAnalysis:
    """
    Class which represents the analysis associated with an expression
    """
    def __init__(self, typ, var_info):
        self.typ: VyperType = typ
        self.var_info: Optional[VarInfo] = var_info

        if var_info is not None and var_info.typ != self.typ:
            raise CompilerPanic("Bad analysis: non-matching types {var_info.typ} / {self.typ}")


    @classmethod
    def from_annotation(
        cls,
        node: vy_ast.VyperNode,
        location: DataLocation = DataLocation.UNSET,
        is_constant: bool = False,
        is_public: bool = False,
        is_immutable: bool = False,
    ) -> "BaseTypeDefinition":
        """
        Generate a `BaseTypeDefinition` instance of this type from `VariableDef.annotation`
        or `AnnAssign.annotation`

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the `annotation` member of a `VariableDef` or `AnnAssign` node.

        Returns
        -------
        BaseTypeDefinition
            BaseTypeDefinition related to the primitive that the method was called on.
        """
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        if node.id != cls._id:
            raise UnexpectedValue("Node id does not match type name")
        return cls.from_annotation(node)

    def validate_modification(
        self,
        mutability: Any, # should be StateMutability, import cycle
        node: vy_ast.VyperNode,
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
