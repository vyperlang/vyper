from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types.units import (
    Unit,
)
from vyper.context.utils import (
    get_index_value,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteralException,
    InvalidTypeException,
    StructureException,
)


"""
# TODO document all this

from_annotation
from_literal

enclosing_scope

compare_type(other):
    Check this type against another type, raise or return None

validate_numeric_op
validate_boolean_op
validate_comparator
validate_implements
validate_call

get_type
get_index_type
get_member_type
"""


class BaseType:
    """
    Private inherited class common to all classes representing vyper types.

    This class is never directly invoked, however all type classes share the
    following attributes:

    Class attributes
    ----------------
    _id : str
        Including this member marks a class as a core type that is directly
        useable in vyper contracts. Classes that do not include it must be
        be initialized via a special metatype class in vyper/context/metatypes.py
    _as_array: bool
        If included and set as True, contracts may use this type may as the base
        of an array by invoking it with a subscript.
    _valid_literal: VyperNode | tuple
        A vyper ast class or tuple of ast classes that can represent valid literals
        for the given type.

    Object attributes
    -----------------
    node : VyperNode
        The vyper AST node associated with the specific type definition.
    namespace : Namespace
        The namespace object that this type exists within.
    """
    __slots__ = ('namespace', )
    enclosing_scope = "builtin"

    def __init__(self, namespace):
        self.namespace = namespace

    def set_unit(self, unit_str):
        raise StructureException(f"Type {self} does not support units")

    def compare_type(self, other):
        return type(self) in (other, type(other))

    def validate_numeric_op(self, node):
        raise InvalidTypeException(f"Invalid type for operand: {self}", node)

    def validate_boolean_op(self, node):
        # TODO
        pass

    def validate_comparator(self, node):
        # TODO
        pass

    def get_member_type(self, node: vy_ast.Attribute):
        raise StructureException(f"Type '{self}' does not support members", node)

    def get_index_type(self, node):
        raise StructureException(f"Type '{self}' does not support indexing", node)

    def validate_call(self, node):
        raise StructureException(f"Type '{self}' is not callable", node)


class ValueType(BaseType):

    """Base class for simple types representing a single value."""

    __slots__ = ()

    def __str__(self):
        return self._id

    @classmethod
    def from_annotation(cls, namespace, node):
        self = cls(namespace)
        names = [i.id for i in node.get_all_children({'ast_type': 'Name'}, True)][1:]
        if len(names) > 1:
            raise StructureException("Invalid type assignment", node)
        if names:
            try:
                self.set_unit(names[0])
            except Exception as e:
                raise StructureException(str(e), node)
        return self

    @classmethod
    def from_literal(cls, namespace, node):
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, cls._valid_literal):
            raise InvalidTypeException(f"Invalid literal type for '{cls}'", node)
        return cls(namespace)


class NumericType(ValueType):

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ('unit',)
    _as_array = True

    def __init__(self, namespace, unit=None):
        self.unit = None
        super().__init__(namespace)
        if unit:
            self.set_unit(unit)

    def set_unit(self, unit_str):
        self.unit = self.namespace[unit_str]
        if not isinstance(self.unit, Unit):
            raise StructureException(f"{unit_str} is not a valid unit type")

    def __str__(self):
        if getattr(self, 'unit', None):
            return f"{self._id}({self.unit})"
        return super().__str__()

    def compare_type(self, other):
        return type(self) is type(other) and self.unit == other.unit

    def validate_numeric_op(self, node):
        if isinstance(node.op, self._invalid_op):
            # TODO: showing ast_type is very vague, maybe add human readable descriptions to nodes?
            raise StructureException(
                f"Unsupported operand for {self}: {node.op.ast_type}", node
            )


class IntegerType(NumericType):

    """Base class for integer numeric types (int128, uint256)."""

    __slots__ = ()
    _valid_literal = vy_ast.Int


class ArrayValueType(ValueType):
    """
    Base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).

    Attributes
    ----------
    length : int | Variable
        The length of the data within the type.
    """
    __slots__ = ('length',)

    def __str__(self):
        return f"{self._id}[{self.length}]"

    def compare_type(self, other):
        return super().compare_type(other) and self.length >= other.length

    @classmethod
    def from_annotation(cls, namespace, node):
        if len(node.get_all_children({'ast_type': "Subscript"}, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", node)
        self = cls(namespace)
        self.length = get_index_value(self.namespace, node.get('slice'))

        if self.length <= 0:
            raise InvalidLiteralException("Slice must be greater than 0", node.slice)
        return self

    @classmethod
    def from_literal(cls, namespace, node):
        self = super().from_literal(namespace, node)
        self.length = len(node.value) or 1
        return self


class CompoundType(BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class MemberType(BaseType):

    """Base class for types that have accessible members."""

    __slots__ = ('_id', 'members',)

    def __init__(self, namespace):
        super().__init__(namespace)
        self.members = OrderedDict()

    def add_member_types(self, **members):
        for name, member in members.items():
            if name in self.members:
                raise StructureException(f"Member {name} already exists in {self}")
            self.members[name] = member

    def get_member_type(self, node: vy_ast.Attribute):
        if node.attr not in self.members:
            raise StructureException(f"Struct {self._id} has no member '{node.attr}'", node)
        return self.members[node.attr]

    # TODO
    # def __eq__(self, other):
    #     return super().__eq__(other) and self.type_class == other.type_class


class EnvironmentVariableType(MemberType):

    _readonly_members = True

    def __str__(self):
        return "environment variable"

    def __init__(self, namespace, _id, members):
        super().__init__(namespace)
        self._id = _id
        self.add_member_types(**members)


class UnionType(set):

    def __str__(self):
        if len(self) == 1:
            return str(next(iter(self)))
        return f"{{{', '.join([str(i) for i in self])}}}"

    def compare_type(self, other):
        if not isinstance(other, UnionType):
            other = [other]

        matches = [i for i in self if any(i.compare_type(x) for x in other)]
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
