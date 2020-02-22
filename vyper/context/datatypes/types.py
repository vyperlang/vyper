from decimal import (
    Decimal,
)
from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    check_call_args,
    get_leftmost_id,
    check_numeric_bounds,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteralException,
    InvalidTypeException,
    StructureException,
)
from vyper.utils import (
    checksum_encode,
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
    node : VyperNode
        The vyper AST node associated with the specific type definition.
    namespace : Namespace
        The namespace object that this type exists within.
    """
    __slots__ = ('namespace', 'node',)

    def __init__(self, namespace, node):
        self.namespace = namespace
        self.node = node

    def __eq__(self, other):
        return type(self) == type(other)

    @property
    def enclosing_scope(self):
        return self.node.enclosing_scope


class _BaseSubscriptType(_BaseType):
    """
    Private inherited class common to all types that use subscript to denote length.

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

    def _introspect(self):
        if len(self.node.get_all_children({'ast_type': "Subscript"}, include_self=True)) > 1:
            raise StructureException("Multidimensional arrays are not supported", self.node)
        self.length = self._get_index_value(self.node.get('slice'))

        if self.length <= 0:
            raise InvalidLiteralException("Slice must be greater than 0", self.node.slice)

    def validate_slice(self, node: vy_ast.Index):
        # validates that a slice referencing this node is valid
        length = self._get_index_value(node)
        if length >= self.length:
            raise StructureException("Array index out of range", node)
        if length < 0:
            raise StructureException("Array index cannot use negative integers", node)
        return length

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
            if not isinstance(typ, (IntegerType, UnsignedIntegerType)):
                raise StructureException(f"Invalid type for Slice: '{typ}'", node)
            if typ.unit:
                raise StructureException(f"Slice value must be unitless, not '{typ.unit}'", node)
            return length.literal_value

        raise StructureException("Slice must be an integer or constant", node)


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

    def _introspect(self):
        names = [i.id for i in self.node.get_all_children({'ast_type': 'Name'}, True)][1:]
        if len(names) > 1:
            raise StructureException("Invalid type assignment", self.node)
        if names:
            try:
                self.unit = self.namespace[names[0]]
            except AttributeError:
                raise StructureException(f"Cannot apply unit to type '{self}'", self.node)

    def validate_literal(self, node):
        if not isinstance(node, vy_ast.Constant):
            raise CompilerPanic(f"Attempted to validate a '{node.ast_type}' node.")
        if not isinstance(node, self._valid_node):
            raise InvalidTypeException(f"Invalid literal type for '{self._id}'", node)


class NumericType(ValueType):

    """Base class for simple numeric types (capable of arithmetic)."""

    __slots__ = ('unit',)
    _as_array = True

    def _introspect(self):
        self.unit = None
        super()._introspect()

    def __str__(self):
        if getattr(self, 'unit', None):
            return f"{self._id}({self.unit})"
        return super().__str__()

    def __eq__(self, other):
        return super().__eq__(other) and self.unit == other.unit


class ArrayValueType(_BaseSubscriptType, ValueType):
    """
    Base class for single-value types which occupy multiple memory slots
    and where a maximum length must be given via a subscript (string, bytes).
    """
    __slots__ = ('length',)

    def _introspect(self):
        if not isinstance(self.node, vy_ast.Subscript):
            raise StructureException(f"{self._id} types must have a maximum length.", self.node)
        super()._introspect()

    def validate_literal(self, node):
        super().validate_literal(node)
        if len(node.value) > self.length:
            raise InvalidLiteralException(
                f"Literal value exceeds the maximum length for {self._id}[{self.length}]",
                node
            )


class CompoundType(_BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class UserDefinedType(_BaseType):

    """Base class for user defined types."""

    __slots__ = ()

    def __init__(self, namespace, node):
        super().__init__(namespace, node)
        key = get_leftmost_id(node)
        self.type_class = namespace[key]

    def __eq__(self, other):
        return super().__eq__(other) and self.type_class == other.type_class

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
    _valid_node = vy_ast.NameConstant

    def validate_literal(self, node):
        super().validate_literal(node)
        if node.value is None:
            raise InvalidLiteralException("Invalid literal for type 'bool'", node)


class AddressType(ValueType):
    __slots__ = ()
    _id = "address"
    _as_array = True
    _valid_node = vy_ast.Hex

    def validate_literal(self, node):
        super().validate_literal(node)
        addr = node.node_source_code
        if len(addr) != 42:
            raise InvalidLiteralException("Invalid literal for type 'address'", node)
        if checksum_encode(addr) != addr:
            raise InvalidLiteralException(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node
            )


class Bytes32Type(ValueType):
    __slots__ = ()
    _id = "bytes32"
    _as_array = True
    _valid_node = vy_ast.Hex

    def validate_literal(self, node):
        super().validate_literal(node)
        value = node.node_source_code
        if len(value) != 66:
            raise InvalidLiteralException("Invalid literal for type bytes32", node)


class IntegerType(NumericType):
    __slots__ = ()
    _id = "int128"
    _valid_node = vy_ast.Int

    def validate_literal(self, node):
        super().validate_literal(node)
        check_numeric_bounds("int128", node)


class UnsignedIntegerType(NumericType):
    __slots__ = ()
    _id = "uint256"
    _valid_node = vy_ast.Int

    def validate_literal(self, node):
        super().validate_literal(node)
        check_numeric_bounds("uint256", node)


class DecimalType(NumericType):
    __slots__ = ()
    _id = "decimal"
    _valid_node = vy_ast.Decimal

    def validate_literal(self, node):
        super().validate_literal(node)
        value = Decimal(node.node_source_code)
        if value.quantize(Decimal('1.0000000000')) != value:
            raise InvalidLiteralException("Vyper supports a maximum of ten decimal points", node)
        check_numeric_bounds("int128", node)


class StringType(ArrayValueType):
    __slots__ = ()
    _id = "string"
    _valid_node = vy_ast.Str


class BytesType(ArrayValueType):
    __slots__ = ()
    _id = "bytes"
    _valid_node = (vy_ast.Bytes, vy_ast.Binary)

    def validate_literal(self, node):
        if not isinstance(node, vy_ast.Binary):
            return super().validate_literal(node)

        value = node.node_source_code
        mod = (len(value)-2) % 8
        if mod:
            raise InvalidLiteralException(
                f"Bit notation requires a multiple of 8 bits / 1 byte. "
                f"{8-mod} bit(s) are missing.",
                node,
            )
        if (len(value)-2) / 8 > self.length:
            raise InvalidLiteralException(
                f"Literal value exceeds the maximum length for {self._id}[{self.length}]", node
            )


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
    _no_value = True

    def __eq__(self, other):
        return (
            super().__eq__(other) and
            self.key_type == other.key_type and
            self.value_type == other.value_type
        )

    def _introspect(self):
        check_call_args(self.node, 2)
        meta_type = self.namespace[self.node.args[0].id]
        self.key_type = meta_type.get_type(self.namespace, self.node.args[0])

        key = get_leftmost_id(self.node.args[1])
        self.value_type = self.namespace[key].get_type(self.namespace, self.node.args[1])

    def __repr__(self):
        return f"map({self.key_type}, {self.value_type})"

    def validate_literal(self, node):
        # TODO - direct assignment is always a no, but with a subscript is ++
        pass


class ArrayType(_BaseSubscriptType, CompoundType):
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
    __slots__ = ('base_type',)

    def __eq__(self, other):
        return super().__eq__(other) and self.base_type == other.base_type

    @property
    def _id(self):
        return self.base_type[0]._id

    def _introspect(self):
        super()._introspect()
        meta_type = self.namespace[self.node.value.id]
        base_type = meta_type.get_type(self.namespace, self.node.value)
        self.base_type = [base_type] * self.length

    def validate_literal(self, node):
        # TODO! IMPORTANT! this does not validate the individual array items
        # which is fine, but it really needs documenting somewhere
        if not isinstance(node, vy_ast.List):
            raise InvalidTypeException(f"Invalid literal type for array", node)
        if len(node.elts) != self.length:
            raise InvalidLiteralException(
                f"Invalid length for literal array, expected {len(node.elts)} got {self.length}",
                node
            )


# User-defined Types
# ------------------
#   These classes are used to represent custom data types that are implemented
#   within a contract, such as structs or contract interfaces.

class StructType(UserDefinedType):
    _as_array = True

    def _introspect(self):
        # TODO
        pass

    def validate_literal(self, node):
        # TODO
        pass


class InterfaceType(UserDefinedType):
    __slots__ = ('address',)
    _as_array = True

    def _introspect(self):
        check_call_args(self.node, 1)
        address = self.node.args[0]
        if isinstance(address, vy_ast.Hex):
            self.address = address.value
        elif isinstance(address, vy_ast.Name):
            self.address = self.namespace[address.id]
            if not isinstance(self.address, AddressType):
                raise
        else:
            raise
        # TODO validate address

    def validate_literal(self, node):
        # TODO
        pass
