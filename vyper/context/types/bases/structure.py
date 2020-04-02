from collections import (
    OrderedDict,
)
from typing import (
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    definitions,
)
from vyper.context.types.utils import (
    get_builtin_type,
)
from vyper.context.utils import (
    get_index_value,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    UnknownAttribute,
)


class BaseType:
    """
    Inherited class common to all classes which represent a Vyper type.

    `BaseType` is never directly invoked. It is inherited by all type classes.
    It includes every possible method that a type can use to define it's
    functionality and so provides a useful blueprint for creating new types.

    Typically when creating a new type you will subclass ValueType or MemberType.

    Class attributes
    ----------------
    _id : str
        Including this member marks a class as a core type that is directly
        useable in vyper contracts. Classes that do not include it must be
        be initialized via a metatype class in `vyper.context.types.user_defined`
    _as_array: bool
        If included and set as `True`, contracts may use this type may as the base
        of an array by invoking it with a subscript.
    """
    __slots__ = ()

    def __init__(self):
        pass

    def _compare_type(self, other: "BaseType") -> bool:
        """
        Compare this type object against another type object.

        Failed comparisons must return `False`, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        are handled by `vyper.context.utils.compare_types`

        Arguments
        ---------
        other : BaseType
            A type object to be compared against this one.

        Returns
        -------
        bool indicating if the types are equivalent.
        """
        return isinstance(self, type(other))

    @property
    def type(self):
        """
        Prevent use of a type as a ValueDefinition.

        This works because ValueDefinition references rely on a `type` member
        for comparisons.
        """
        raise StructureException(f"Invalid use of {self} as a reference")

    def from_annotation(self, node: vy_ast.VyperNode) -> "BaseType":
        """
        Generate an instance of this type from `AnnAssign.annotation`

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the `annotation` member of an `AnnAssign` node.

        Returns
        -------
        A new instance of the same type that the method was called on.
        """
        raise StructureException(f"Type {self} cannot be generated from annotation", node)

    def from_literal(self, node: vy_ast.Constant) -> "BaseType":
        """
        Generate an instance of this type from a `Constant`.

        Arguments
        ---------
        node : Constant
            A Vyper `Constant` AST node.

        Returns
        -------
        A new instance of the same type that the method was called on.
        """
        raise StructureException(f"Type {self} cannot be generated from a literal", node)

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]) -> None:
        """
        Validate a numeric operation for this type.

        Arguments
        ---------
        node : UnaryOp | BinOp
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
        raise CompilerPanic(f"Type {self} cannot validate an implements statement")

    def fetch_call_return(self, node: vy_ast.Call) -> Union[tuple, "BaseType", None]:
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
        BaseType | tuple, optional
            Type object(s) generated as a result of the call.
        """
        raise StructureException(f"Type '{self}' is not callable", node)

    def get_index_type(self, node: vy_ast.Index) -> "BaseType":
        """
        Validate an index reference and return the given type at the index.

        Arguments
        ---------
        node : Index
            Vyper ast node from the `slice` member of a Subscript node.

        Returns
        -------
        A type object for the value found at the given index. Raises an
        exception if the index is invalid for this type.
        """
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def get_type_member(self, node: vy_ast.Attribute) -> "BaseType":
        """
        Validate an attribute reference and return the given type for the member.

        Arguments
        ---------
        node: Attribute
            Vyper ast Attribute node representing the member being accessed.

        Returns
        -------
        A type object for the value of the given member. Raises if the member
        does not exist for the given type.
        """
        raise StructureException(f"Type '{self}' does not support members", node)

    def add_type_members(self, **members: dict) -> None:
        """
        Adds new members to the type.

        Types which include this method should subclass `MemberType`.

        Arguments
        ---------
        **members : dict
            Dictionary of members to add in the form `{"field name": type_object}`

        Returns
        -------
        None
        """
        raise CompilerPanic(f"Type '{self}' does not support members")

    def validate_modification(self, node: Union[vy_ast.Assign, vy_ast.AugAssign]) -> None:
        raise InvalidOperation("Cannot assign to or modify a type", node)


class ValueType(BaseType):
    """
    Base class for simple types representing a single value.

    Class attributes
    ----------------
    _valid_literal: VyperNode | tuple
        A vyper ast class or tuple of ast classes that can represent valid literals
        for the given type. Including this attribute will allow literal values to be
        cast as this type.
    """
    __slots__ = ()

    def __repr__(self):
        return self._id

    @classmethod
    def from_annotation(cls, node: vy_ast.Name) -> "ValueType":
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        return cls()

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> "ValueType":
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, cls._valid_literal):
            raise InvalidLiteral(f"Invalid literal type for {cls.__name__}", node)
        return cls()


class MemberType(BaseType):
    """
    Base class for types that have accessible members.

    Class attributes
    ----------------
    _readonly_members : bool
        If True, members of this type are considered read-only and cannot be assigned
        new values.

    Object attributes
    -----------------
    members : OrderedDict
        An dictionary of members for the given type in the format `{name: ValueDefinition}`.
    """
    __slots__ = ('_id', 'members',)

    def __init__(self):
        super().__init__()
        self.members = OrderedDict()

    def add_type_members(self, **members: dict):
        for name, member in members.items():
            try:
                self.get_type_member(name)
            except UnknownAttribute:
                self.members[name] = member
            else:
                raise NamespaceCollision(f"Member {name} already exists in {self}")

    def get_type_member(self, key: str):
        if key in self.members:
            return self.members[key]
        if key in getattr(self, '_type_members', {}):
            type_ = get_builtin_type(self._type_members[key])
            return definitions.Reference.from_type(type_, f"{self}.{key}", is_readonly=True)

        raise UnknownAttribute(f"{self} has no member '{key}'")

    def __repr__(self):
        return f"{self._id}"


class ArrayValueType(ValueType):
    """
    Base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).

    Types for literals have an inferred minimum length. For example, `b"hello"`
    has a length of 5 of more and so can be used in an operation with `bytes[5]`
    or `bytes[10]`, but not `bytes[4]`. Upon comparison to a fixed length type,
    the minimum length is discarded and the type assumes the fixed length it was
    compared against.

    Attributes
    ----------
    _length : int
        The maximum allowable length of the data within the type.
    _min_length: int
        The minimum length of the data within the type. Used when the type
        is applied to a literal definition.
    """
    __slots__ = ('_length', '_min_length')

    def __repr__(self):
        return f"{self._id}[{self.length}]"

    def __init__(self, length: int = 0):
        super().__init__()
        self._length = length
        self._min_length = length

    @property
    def length(self):
        """
        Property method used to check the length of a type.
        """
        if self._length:
            return self._length
        return self._min_length

    def set_length(self, length):
        """
        Sets the exact length of the type.

        May only be called once, and only on a type that does not yet have
        a fixed length.
        """
        if self._length:
            raise CompilerPanic("Type already has a fixed length")
        self._length = length
        self._min_length = length

    def set_min_length(self, min_length):
        """
        Sets the minimum length of the type.

        May only be used to increase the minimum length. May not be called if
        an exact length has been set.
        """
        if self._length:
            raise CompilerPanic("Type already has a fixed length")
        if self._min_length > min_length:
            raise CompilerPanic("Cannot reduce the min_length of ArrayValueType")
        self._min_length = min_length

    def _compare_type(self, other):
        if not super()._compare_type(other):
            return False

        # when comparing two literals, both now have an equal min-length
        if not self._length and not other._length:
            min_length = max(self._min_length, other._min_length)
            self.set_min_length(min_length)
            other.set_min_length(min_length)
            return True

        # comparing a defined length to a literal causes the literal to have a fixed length
        if self._length:
            if not other._length:
                other.set_length(max(self._length, other._min_length))
            return self._length >= other._length

        return other._compare_type(self)

    @classmethod
    def from_annotation(cls, node):
        if len(node.get_descendants(vy_ast.Subscript, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", node)

        length = get_index_value(node.get('slice') or node)
        return cls(length)

    @classmethod
    def from_literal(cls, node):
        self = super().from_literal(node)

        if isinstance(node, vy_ast.Binary):
            length = (len(node.value)-2) // 8
        elif isinstance(node, vy_ast.Hex):
            length = len(node.value) // 2 - 1
        else:
            length = len(node.value)

        self.set_min_length(length)
        return self


class EnvironmentVariableType(MemberType):

    """Special base class for environment variable member types (msg, block, etc)"""

    _readonly_members = True

    def __repr__(self):
        return "environment variable"

    def __init__(self, _id, members):
        super().__init__()
        self._id = _id
        self.add_type_members(**members)
