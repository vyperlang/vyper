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
    namespace,
)
from vyper.context.types.units import (
    Unit,
)
from vyper.context.utils import (
    check_call_args,
    get_index_value,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteralException,
    InvalidTypeException,
    StructureException,
)


class _BaseType:
    """
    Private inherited class common to all classes representing vyper types.

    This class is never directly invoked. It is inherited by all type classes.
    It includes every possible method that a type can use to define it's
    functionality and so provides a useful blueprint when creating new types.

    Usually if you are creating a new type you will want to subclass from
    ValueType, CompoundType or MemberType.

    Class attributes
    ----------------
    _id : str
        Including this member marks a class as a core type that is directly
        useable in vyper contracts. Classes that do not include it must be
        be initialized via a special metatype class in vyper/context/metatypes.py
    _as_array: bool
        If included and set as True, contracts may use this type may as the base
        of an array by invoking it with a subscript.
    _no_value: bool
        If included and True, this type cannot be directly assigned to. Used for mappings.
    """
    __slots__ = ()

    def __init__(self):
        pass

    def _compare_type(self, other: "_BaseType"):
        """
        Compares this type object against another type object.

        Failed comparisons should always return False, not raise an exception.

        This method is not intended to be called directly. Type comparisons
        should be handled by vyper.context.utils.compare_types

        Arguments
        ---------
        other : BaseType
            A type object to be compared against this one.

        Returns
        -------
        bool indicating if the types are equivalent.
        """
        return type(self) in (other, type(other))

    def from_annotation(self, node: vy_ast.VyperNode):
        """
        Generates an instance of this type from AnnAssign.annotation

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the .annotation member of an AnnAssign node.

        Returns
        -------
        A new instance of the same type that the method was called on.
        """
        raise CompilerPanic(f"Type {self} cannot be generated from annotation")

    def from_literal(self, node: vy_ast.Constant):
        """
        Generates a new instance of this type from a constant.

        Arguments
        ---------
        node : Constant
            A vyper ast node of type Constant.

        Returns
        -------
        A new instance of the same type that the method was called on.
        """
        raise CompilerPanic(f"Type {self} cannot be generated from a literal")

    def set_unit(self, unit_str: str):
        """
        Applies a unit to this type object. Raises if the type does not support units.

        Arguments
        ---------
        unit_str : str
            The name of the unit to be applied.

        Returns
        -------
        None. A failed validation should raise an exception.
        """
        raise StructureException(f"Type {self} does not support units")

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]):
        """
        Validates a numeric operation for this type.

        Arguments
        ---------
        node : UnaryOp | BinOp
            Vyper ast node of the numeric operation to be validated.

        Returns
        -------
        None. A failed validation should raise an exception.
        """
        raise InvalidTypeException(f"Invalid type for operand: {self}", node)

    def validate_boolean_op(self, node: vy_ast.BoolOp):
        """
        Validates a boolean operation for this type.

        Arguments
        ---------
        node : BoolOp
            Vyper ast node of the boolean operation to be validated.

        Returns
        -------
        None. A failed validation should raise an exception.
        """
        # TODO this isn't implemented anywhere
        raise InvalidTypeException(f"Invalid type for operand: {self}", node)

    def validate_comparator(self, node: vy_ast.Compare):
        """
        Validates a comparator for this type.

        Arguments
        ---------
        node : Compare
            Vyper ast node of the comparator to be validated.

        Returns
        -------
        None. A failed validation should raise an exception.
        """
        if not isinstance(node.ops[0], (vy_ast.Eq, vy_ast.NotEq)):
            raise InvalidTypeException(f"Invalid type for comparator: {self}", node)

    def validate_implements(self, node: vy_ast.AnnAssign):
        """
        Validates an implements statement.

        This method is unique to user-defined interfaces. It should not be
        included in other types.

        Arguments
        ---------
        node : AnnAssign
            Vyper ast node of the implements statement being validated.

        Returns
        -------
        None. A failed validation should raise an exception.
        """
        raise CompilerPanic(f"Type {self} cannot validate an implements statement", node)

    def get_call_return_type(self, node: vy_ast.Call):
        """
        Validates a call to this type and returns the result.

        This method should raise if the type is not callable or the call arguments
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

    def get_index_type(self, node: vy_ast.VyperNode):
        """
        Validates an index reference and returns the given type at the index.

        Arguments
        ---------
        node : VyperNode
            Vyper ast node from the .slice member of a Subscript node.

        Returns
        -------
        A type object for the value found at the given index. Raises an
        exception if the index is invalid for this type.
        """
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def get_member_type(self, node: vy_ast.Attribute):
        """
        Validates a attribute reference and returns the given type for the member.

        Arguments
        ---------
        node: Attribute
            Vyper ast Attribute node representing the member being accessed.

        Returns
        -------
        A type object for the value of the given member. Raises an exception
        if the member does not exist for the given type.
        """
        raise StructureException(f"Type '{self}' does not support members", node)

    def add_member_types(self, **members: dict):
        """
        Adds new members to the type.

        Types which include this method should subclass MemberType.

        Arguments
        ---------
        **members : dict
            Dictionary of members to add in the form name: type

        Returns
        -------
        None
        """
        raise CompilerPanic(f"Type '{self}' does not support members")


class ValueType(_BaseType):
    """
    Base class for simple types representing a single value.

    Object attributes
    -----------------
    is_value_type : bool
        Identifies a type object as a ValueType. `getattr(obj, 'is_value_type', None)`
        is preferrable to `isinstance(obj, ValueType)` because it also works for
        UnionType objects.
    is_bytes
    is_integer
    is_numeric : bool
        Identifies a type object as BytesType, IntegerType or NumericType. Has the
        same use case as `is_value_type`.

    Class attributes
    ----------------
    _valid_literal: VyperNode | tuple
        A vyper ast class or tuple of ast classes that can represent valid literals
        for the given type. Including this attribute will allow literal values to be
        cast as this type.
    """
    __slots__ = ()
    is_value_type = True

    def __str__(self):
        return self._id

    @classmethod
    def from_annotation(cls, node):
        if not isinstance(node, vy_ast.Name):
            raise StructureException("Invalid type assignment", node)
        return cls()

    @classmethod
    def from_literal(cls, node):
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, cls._valid_literal):
            raise InvalidTypeException(f"Invalid literal type for '{cls}'", node)
        return cls()


class CompoundType(_BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class MemberType(_BaseType):
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
        An dictionary of members for the given type in the format {name: type object}.
        A member can be a type object or a definition.
    """
    __slots__ = ('_id', 'members',)

    def __init__(self):
        super().__init__()
        self.members = OrderedDict()

    def add_member_types(self, **members: dict):
        for name, member in members.items():
            if name in self.members:
                raise StructureException(f"Member {name} already exists in {self}")
            self.members[name] = member

    def get_member_type(self, node: vy_ast.Attribute):
        if node.attr not in self.members:
            raise StructureException(f"Struct {self._id} has no member '{node.attr}'", node)
        return self.members[node.attr]

    def __str__(self):
        return f"{self._id}"


class NumericType(ValueType):

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ('unit',)
    _as_array = True
    is_numeric = True

    def __init__(self, unit=None):
        self.unit = None
        super().__init__()
        if unit:
            self.set_unit(unit)

    @classmethod
    def from_annotation(cls, node):
        if isinstance(node, vy_ast.Name):
            return super().from_annotation(node)
        check_call_args(node, 1)
        self = super().from_annotation(node.func)
        try:
            self.set_unit(node.args[0].id)
        except Exception as e:
            raise StructureException(str(e), node)
        return self

    def set_unit(self, unit_str):
        self.unit = namespace[unit_str]
        if not isinstance(self.unit, Unit):
            raise StructureException(f"{unit_str} is not a valid unit type")

    def __str__(self):
        if getattr(self, 'unit', None):
            return f"{self._id}({self.unit})"
        return super().__str__()

    def _compare_type(self, other):
        if type(self) is not type(other):
            return False
        if not hasattr(self, 'unit') or not hasattr(other, 'unit'):
            return True
        return self.unit == other.unit

    def validate_numeric_op(self, node):
        if isinstance(node.op, self._invalid_op):
            # TODO: showing ast_type is very vague, maybe add human readable descriptions to nodes?
            raise StructureException(
                f"Unsupported operand for {self}: {node.op.ast_type}", node
            )

    def validate_comparator(self, node: vy_ast.Compare):
        return

    @classmethod
    def from_literal(cls, node):
        # TODO do this in a less hacky way
        self = super().from_literal(node)
        del self.unit
        return self


class IntegerType(NumericType):

    """Base class for integer numeric types (int128, uint256)."""

    __slots__ = ()
    _valid_literal = vy_ast.Int
    is_integer = True


class BytesType(ValueType):

    """Base class for bytes types (bytes32, bytes[])."""

    __slots__ = ()
    is_bytes = True


class ArrayValueType(ValueType):
    """
    Base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).

    Attributes
    ----------
    length : int
        The length of the data within the type.
    min_length: int
        The minimum length of the data within the type. Used when the type
        is applied to a literal definition.
    """
    __slots__ = ('length', 'min_length')

    def __str__(self):
        return f"{self._id}[{self.length}]"

    def __init__(self, length: int = 0):
        super().__init__()
        self.length = length
        self.min_length = length

    def _compare_type(self, other):
        if not super()._compare_type(other):
            return False

        # when comparing two literals, both now have an equal min-length
        if not self.length and not other.length:
            min_length = max(self.min_length, other.min_length)
            self.min_length = min_length
            other.min_length = min_length
            return True

        # comparing a defined length to a literal causes the literal to have a fixed length
        if self.length:
            if not other.length:
                other.length = max(self.length, other.min_length)
            return self.length >= other.length

        return other._compare_type(self)

    @classmethod
    def from_annotation(cls, node):
        if len(node.get_all_children({'ast_type': "Subscript"}, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", node)
        length = get_index_value(node.get('slice') or node)
        if length <= 0:
            raise InvalidLiteralException("Slice must be greater than 0", node.slice)

        return cls(length)

    @classmethod
    def from_literal(cls, node):
        self = super().from_literal(node)
        self.min_length = len(node.value) or 1
        return self


class EnvironmentVariableType(MemberType):

    """Base class for environment variable member types (msg, block, etc)"""

    _readonly_members = True

    def __str__(self):
        return "environment variable"

    def __init__(self, _id, members):
        super().__init__()
        self._id = _id
        self.add_member_types(**members)


class UnionType(set):
    """
    Set subclass for literal values where the final type has not yet been determined.

    When this object is compared to another type, invalid types for the comparison
    are removed. For eaxmple, the literal value 1 will initially be a UnionType of
    {int128, uint256}. If the type is then compared to -1 it is now considered to
    be int128 and subsequent comparisons to uint256 will return False.
    """
    def __str__(self):
        if len(self) == 1:
            return str(next(iter(self)))
        return f"{{{', '.join([str(i) for i in self])}}}"

    @property
    def is_bytes(self):
        return all(hasattr(i, 'is_bytes') for i in self)

    @property
    def is_integer(self):
        return all(hasattr(i, 'is_integer') for i in self)

    @property
    def is_numeric(self):
        return all(hasattr(i, 'is_numeric') for i in self)

    @property
    def is_value_type(self):
        return all(hasattr(i, 'is_value_type') for i in self)

    def _compare_type(self, other):
        if not isinstance(other, UnionType):
            other = [other]

        matches = [i for i in self if any(i._compare_type(x) for x in other)]
        if not matches:
            return False

        self.intersection_update(matches)
        return True

    def _validate(self, node, attr):
        for typ in list(self):
            try:
                getattr(typ, attr)(node)
            except Exception:
                self.remove(typ)
                if not self:
                    raise

    def validate_comparator(self, node):
        self._validate(node, 'validate_comparator')

    def validate_boolean_op(self, node):
        self._validate(node, 'validate_boolean_op')

    def validate_numeric_op(self, node):
        self._validate(node, 'validate_numeric_op')
