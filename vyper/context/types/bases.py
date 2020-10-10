import copy
from collections import OrderedDict
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Type, Union

from vyper import ast as vy_ast
from vyper.context.types.abstract import AbstractDataType
from vyper.exceptions import (
    CompilerPanic,
    ImmutableViolation,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    UnexpectedNodeType,
    UnexpectedValue,
    UnknownAttribute,
)


class DataLocation(Enum):
    UNSET = 0
    MEMORY = 1
    STORAGE = 2
    CALLDATA = 3


class BasePrimitive:
    """
    Base class for primitive type classes.

    Primitives are objects that are invoked when applying a type to a variable.
    They must contain a `from_annotation` (and optionally `from_literal`) method
    that returns their equivalent `BaseTypeDefinition` object.

    Attributes
    ----------
    _id : str
        The name of the type.
    _type : BaseTypeDefinition
        The related `BaseTypeDefinition` class generated from this primitive
    _as_array: bool, optional
        If `True`, this type can be used as the base member for an array.
    _valid_literal : Tuple
        A tuple of Vyper ast classes that may be assigned this type.
    """

    _id: str
    _type: Type["BaseTypeDefinition"]
    _valid_literal: Tuple

    @classmethod
    def from_annotation(
        cls,
        node: Union[vy_ast.Name, vy_ast.Call],
        location: DataLocation = DataLocation.UNSET,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> "BaseTypeDefinition":
        """
        Generate a `BaseTypeDefinition` instance of this type from `AnnAssign.annotation`

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the `annotation` member of an `AnnAssign` node.

        Returns
        -------
        BaseTypeDefinition
            BaseTypeDefinition related to the primitive that the method was called on.
        """
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        if node.id != cls._id:
            raise UnexpectedValue("Node id does not match type name")
        return cls._type(location, is_immutable, is_public)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> "BaseTypeDefinition":
        """
        Generate a `BaseTypeDefinition` instance of this type from a literal constant.

        This method is called on every primitive class in order to determine
        potential types for a `Constant` AST node.

        Types that may be assigned from literals should include a `_valid_literal`
        attribute, containing a list of AST node classes that may be valid for
        this type. If the `_valid_literal` attribute is not included, the type
        cannot be assigned to a literal.

        Arguments
        ---------
        node : VyperNode
            `Constant` Vyper ast node, or a list or tuple of constants.

        Returns
        -------
        BaseTypeDefinition
            BaseTypeDefinition related to the primitive that the method was called on.
        """
        if not isinstance(node, vy_ast.Constant):
            raise UnexpectedNodeType(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, cls._valid_literal):
            raise InvalidLiteral(f"Invalid literal type for {cls.__name__}", node)
        return cls._type()

    @classmethod
    def compare_type(
        cls, other: Union["BaseTypeDefinition", "BasePrimitive", AbstractDataType]
    ) -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by methods in `vyper.context.validation.utils`

        Arguments
        ---------
        other : BaseTypeDefinition
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, cls._type)

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
    def get_index_type(self, node: vy_ast.Index) -> None:
        # always raises - do not implement in inherited classes
        raise StructureException("Types cannot be indexed", node)

    @classmethod
    def get_member(cls, key: str, node: vy_ast.Attribute) -> None:
        # always raises - do not implement in inherited classes
        raise StructureException("Types do not have members", node)

    @classmethod
    def validate_modification(cls, node: Union[vy_ast.Assign, vy_ast.AugAssign]) -> None:
        # always raises - do not implement in inherited classes
        raise InvalidOperation("Cannot assign to a type", node)


class BaseTypeDefinition:
    """
    Base class for type definition classes.

    Type definitions are objects that represent the type of a specific object
    within a contract. They are usually derived from a `BasePrimitive` counterpart.

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
    is_immutable : bool, optional
        If `True`, the value of this object cannot be modified after assignment.
    """

    is_dynamic_size = False

    def __init__(
        self,
        location: DataLocation = DataLocation.UNSET,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        self.location = location
        self.is_immutable = is_immutable
        self.is_public = is_public

    def from_annotation(self, node: vy_ast.VyperNode, **kwargs: Any) -> None:
        # always raises, user should have used a primitive
        raise StructureException("Value is not a type", node)

    def compare_type(
        self, other: Union["BaseTypeDefinition", BasePrimitive, AbstractDataType]
    ) -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by methods in `vyper.context.validation.utils`

        Arguments
        ---------
        other : BaseTypeDefinition
            Another type object to be compared against this one.

        Returns
        -------
        bool
            Indicates if the types are equivalent.
        """
        return isinstance(other, type(self))

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

    def get_index_type(self, node: vy_ast.Index) -> "BaseTypeDefinition":
        """
        Validate an index reference and return the given type at the index.

        Arguments
        ---------
        node : Index
            Vyper ast node from the `slice` member of a Subscript node.

        Returns
        -------
        BaseTypeDefinition
            Type object for value at the given index.
        """
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def get_member(self, key: str, node: vy_ast.Attribute) -> "BaseTypeDefinition":
        """
        Validate an attribute reference and return the given type for the member.

        Arguments
        ---------
        key : str
            Name of the member being accessed.
        node: Attribute
            Vyper ast Attribute node representing the member being accessed.

        Returns
        -------
        BaseTypeDefinition
            A type object for the value of the given member. Raises if the member
            does not exist for the given type.
        """
        raise StructureException(f"Type '{self}' does not support members", node)

    def validate_modification(self, node: Union[vy_ast.Assign, vy_ast.AugAssign]) -> None:
        """
        Validate an attempt to modify this value.

        Raises if the value is a constant or involves an invalid operation.

        Arguments
        ---------
        node : Assign | AugAssign
            Vyper ast node of the modifying action.
        """
        if self.location == DataLocation.CALLDATA:
            raise ImmutableViolation("Cannot write to calldata", node)
        if self.is_immutable:
            raise ImmutableViolation("Immutable value cannot be written to", node)
        if isinstance(node, vy_ast.AugAssign):
            self.validate_numeric_op(node)

    def get_signature(self) -> Tuple[Tuple, Optional["BaseTypeDefinition"]]:
        raise CompilerPanic("Method must be implemented by the inherited class")

    def compare_signature(self, other: "BaseTypeDefinition") -> bool:
        """
        Compare the signature of this type with another type.

        Used when determining if an interface has been implemented. This method
        should not be directly implemented by any inherited classes.
        """

        if not self.is_public:
            return False

        arguments, return_type = self.get_signature()
        other_arguments, other_return_type = other.get_signature()

        if len(arguments) != len(other_arguments):
            return False
        for a, b in zip(arguments, other_arguments):
            if not a.compare_type(b):
                return False
        if return_type and not return_type.compare_type(other_return_type):  # type: ignore
            return False

        return True


class ValueTypeDefinition(BaseTypeDefinition):
    """
    Base class for types representing a single value.

    Class attributes
    ----------------
    _valid_literal: VyperNode | Tuple
        A vyper ast class or tuple of ast classes that can represent valid literals
        for the given type. Including this attribute will allow literal values to be
        assigned this type.
    """

    def __repr__(self):
        return self._id

    def get_signature(self):
        return (), self


class MemberTypeDefinition(ValueTypeDefinition):
    """
    Base class for types that have accessible members.

    Class attributes
    ----------------
    _type_members : Dict[str, BaseType]
        Dictionary of members common to all values of this type.

    Object attributes
    -----------------
    members : OrderedDict[str, BaseType]
        Dictionary of members for the given type.
    """

    _type_members: Dict

    def __init__(
        self,
        location: DataLocation = DataLocation.UNSET,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        super().__init__(location, is_immutable, is_public)
        self.members: OrderedDict = OrderedDict()

    def add_member(self, name: str, type_: BaseTypeDefinition) -> None:
        if name in self.members:
            raise NamespaceCollision(f"Member '{name}' already exists in {self}")
        if name in getattr(self, "_type_members", []):
            raise NamespaceCollision(f"Member '{name}' already exists in {self}")
        self.members[name] = type_

    def get_member(self, key: str, node: vy_ast.VyperNode) -> BaseTypeDefinition:
        if key in self.members:
            return self.members[key]
        elif key in getattr(self, "_type_members", []):
            type_ = copy.deepcopy(self._type_members[key])
            type_.location = self.location
            type_.is_immutable = self.is_immutable
            return type_
        raise UnknownAttribute(f"{self} has no member '{key}'", node)

    def __repr__(self):
        return f"{self._id}"


class IndexableTypeDefinition(BaseTypeDefinition):
    """
    Base class for indexable types such as arrays and mappings.

    Attributes
    ----------
    key_type: BaseType
        Type representing the index value for this object.
    value_type : BaseType
        Type representing the value(s) contained in this object.
    _id : str
        Name of the type.
    """

    def __init__(
        self,
        value_type: BaseTypeDefinition,
        key_type: BaseTypeDefinition,
        _id: str,
        location: DataLocation = DataLocation.UNSET,
        is_immutable: bool = False,
        is_public: bool = False,
    ) -> None:
        super().__init__(location, is_immutable, is_public)
        self.value_type = value_type
        self.key_type = key_type
        self._id = _id

    def get_signature(self) -> Tuple[Tuple, Optional[BaseTypeDefinition]]:
        new_args, return_type = self.value_type.get_signature()
        return (self.key_type,) + new_args, return_type
