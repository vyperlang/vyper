
from vyper import (
    ast as vy_ast,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteralException,
    InvalidTypeException,
    StructureException,
)


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

    def __eq__(self, other):
        return type(self) in (other, type(other))

    # @property
    # def enclosing_scope(self):
    #     return self.node.enclosing_scope

    def validate_numeric_op(self, node):
        raise InvalidTypeException(f"Invalid type for operand: {self}", node)

    def validate_boolean_op(self, node):
        # TODO
        pass

    def validate_compare(self, node):
        # TODO
        pass


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
                self.unit = namespace[names[0]]
            except AttributeError:
                raise StructureException(f"Cannot apply unit to type '{cls}'", node)
        return self

    def validate_literal(self, node):
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, self._valid_literal):
            raise InvalidTypeException(f"Invalid literal type for '{self}'", node)


class NumericType(ValueType):

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ('unit',)
    _as_array = True

    @classmethod
    def from_annotation(cls, namespace, node):
        obj = super().from_annotation(namespace, node)
        if not hasattr(obj, 'unit'):
            obj.unit = None
        return obj

    def __str__(self):
        if getattr(self, 'unit', None):
            return f"{self._id}({self.unit})"
        return super().__str__()

    def __eq__(self, other):
        if not self.unit:
            return super().__eq__(other)
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

    def __eq__(self, other):
        return super().__eq__(other) and self.length == other.length

    @classmethod
    def from_annotation(cls, namespace, node):
        if len(node.get_all_children({'ast_type': "Subscript"}, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", node)
        self = cls(namespace)
        self.length = self._get_index_value(node.get('slice'))

        if self.length <= 0:
            raise InvalidLiteralException("Slice must be greater than 0", node.slice)
        return self

    def _get_index_value(self, node):
        if not isinstance(node, vy_ast.Index):
            raise

        if isinstance(node.value, vy_ast.Int):
            return node.value.value

        if isinstance(node.value, vy_ast.Name):
            slice_name = node.value.id
            length = self.namespace[slice_name]

            if not length.is_constant:
                raise StructureException("Slice must be an integer or constant", node)

            typ = length.type
            if not isinstance(typ, IntegerType):
                raise StructureException(f"Invalid type for Slice: '{typ}'", node)
            if typ.unit:
                raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
            return length.literal_value

        raise StructureException("Slice must be an integer or constant", node)

    def validate_literal(self, node):
        super().validate_literal(node)
        if len(node.value) > self.length:
            raise InvalidLiteralException(
                f"Literal value exceeds the maximum length for {self}",
                node
            )


class CompoundType(BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class UserDefinedType(BaseType):

    """Base class for user defined types."""

    __slots__ = ('node', '_id',)

    def __init__(self, namespace, node):
        super().__init__(namespace)
        self.node = node

    @property
    def enclosing_scope(self):
        return self.node.enclosing_scope

    # TODO
    # def __eq__(self, other):
    #     return super().__eq__(other) and self.type_class == other.type_class
