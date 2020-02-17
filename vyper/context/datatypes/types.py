from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    get_leftmost_id,
)
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
)


class _BaseType:
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

    Object attributes
    -----------------
    _node : VyperNode
        The vyper AST node associated with the specific type definition.
    namespace : Namespace
        The namespace object that this type exists within.
    """
    __slots__ = ('namespace', '_node')

    def __init__(self, namespace, node):
        self.namespace = namespace
        self._node = node

    def introspect(self):
        names = [i.id for i in self._node.get_all_children({'ast_type': 'Name'}, True)][1:]
        if len(names) > 1:
            raise StructureException("Invalid type assignment", self._node)
        if names:
            try:
                self.unit = self.namespace[names[0]]
            except AttributeError:
                raise StructureException(f"Cannot apply unit to type '{self}'", self._node)


# Type Categories
# ---------------
#   These classes define common characteristics between similar vyper types.
#   They are not directly instantiated, but can be imported and used with
#   isinstance() to confirm that a specific type is of the given category.

class ValueType(_BaseType):

    """Base class for simple types representing a single value."""

    __slots__ = ()

    def __str__(self):
        return self._id


class NumericType(ValueType):

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ('unit',)
    _as_array = True

    def introspect(self):
        self.unit = None
        super().introspect()

    def __str__(self):
        if hasattr(self, 'unit'):
            return f"{self._id}({self.unit})"
        return super().__str__()


class ArrayValueType(ValueType):
    """
    Base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).
    """
    __slots__ = ('length',)

    def introspect(self):
        # TODO
        pass


class CompoundType(_BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class UserDefinedType(_BaseType):

    """Base class for user defined types."""

    __slots__ = ()

    def __init__(self, namespace, node, type_class):
        super().__init__(namespace, node)
        self.type_class = type_class

    @property
    def _id(self):
        return self.type_class._id


# Builtin Types
# -------------
#   These classes define the core data types within Vyper.

class BoolType(ValueType):
    __slots__ = ()
    _id = "bool"
    _as_array = True


class AddressType(ValueType):
    __slots__ = ()
    _id = "address"
    _as_array = True


class Bytes32Type(ValueType):
    __slots__ = ()
    _id = "bytes32"
    _as_array = True


class IntegerType(NumericType):
    __slots__ = ()
    _id = "int128"


class UnsignedIntegerType(NumericType):
    __slots__ = ()
    _id = "uint256"


class DecimalType(NumericType):
    __slots__ = ()
    _id = "decimal"


class StringType(ArrayValueType):
    __slots__ = ()
    _id = "string"


class BytesType(ArrayValueType):
    __slots__ = ()
    _id = "bytes"


class MappingType(CompoundType):
    """
    Represents a storage mapping type: `map(key_type, value_type)`

    Attributes
    ----------
    key_type : ValueType
        Type object representing the mapping key.
    value_type : _BaseType
        Type object representing the mapping value.
    """
    __slots__ = ('key_type', 'value_type')
    _id = "map"

    def introspect(self):
        self.key_type = self.namespace[self._node.args[0].id].get_type(self._node.args[0])

        key = get_leftmost_id(self._node.args[1])
        self.value_type = self.namespace[key].get_type(self._node.args[1])

        self.key_type.introspect()
        self.value_type.introspect()

    def __repr__(self):
        return f"map({self.key_type}, {self.value_type})"


class EventType(CompoundType):
    """
    Represents an event: `EventName({attr: value, .. })`

    Attributes
    ----------
    TODO
    """
    __slots__ = ()
    _id = "event"

    def introspect(self):
        # TODO
        pass


class ArrayType(CompoundType):
    """
    Represents a fixed-length array with a single common type for all items.

    This class is not directly instantiated. BuiltinMetaType returns an ArrayType
    object when a base type that includes the `_as_array` member is referenced, and
    that reference includes a subscript.

    Attributes
    ----------
    base_type : BaseType
        Type object representing the base type for the array.
    length : int | Variable
        The number of items in the array.
    """
    __slots__ = ('base_type', 'length')

    @property
    def _id(self):
        return self.base_type._id

    def __str__(self):
        return f"{self._id}[{self.length}]"

    def introspect(self):
        # if array index is a Name, we have to check constants
        node = self._node.get_all_children({'ast_type': "Subscript"}, include_self=True)[0]
        self.base_type = self.namespace[node.value.id].get_type(node.value)

        if isinstance(node.get('slice.value'), vy_ast.Name):
            slice_name = node.slice.value.id
            self.length = self.namespace[slice_name]
            typ = self.length.type
            if not isinstance(typ, (IntegerType, UnsignedIntegerType)):
                raise StructureException(f"Invalid type for Slice: '{typ}'", node.slice)
            if typ.unit:
                raise StructureException(
                    f"Slice value must be unitless, not '{typ.unit}'", node.slice
                )
            self.length.introspect()
            if not self.length.is_constant:
                raise StructureException("Slice must be an integer or constant", node.slice)

        elif isinstance(node.get('slice.value'), vy_ast.Int):
            self.length = node.slice.value.n
            if self.length <= 0:
                raise InvalidLiteralException("Slice must be greater than 0", node.slice)

        else:
            raise StructureException("Slice must be an integer or constant", node.slice)


# User-defined Types
# ------------------
#   These classes are used to represent custom data types that are implemented
#   within a contract, such as structs or contract interfaces.

class StructType(UserDefinedType):
    _as_array = True

    def introspect(self):
        # TODO
        pass


class InterfaceType(UserDefinedType):
    _as_array = True

    def introspect(self):
        # TODO
        pass
