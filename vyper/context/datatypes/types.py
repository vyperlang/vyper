from collections import (
    OrderedDict,
)
from decimal import (
    Decimal,
)
from vyper import (
    ast as vy_ast,
)
from vyper.context.utils import (
    check_call_args,
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
from vyper.context.datatypes.functions import (
    Function,
)
from vyper.context import datatypes


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


class CompoundType(_BaseType):

    """Base class for types which represent multiple values."""

    __slots__ = ()


class UserDefinedType(_BaseType):

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


# Builtin Types
# -------------
#   These classes define the core data types within Vyper.

class BoolType(ValueType):
    __slots__ = ()
    _id = "bool"
    _as_array = True
    _valid_literal = vy_ast.NameConstant

    def validate_literal(self, node):
        super().validate_literal(node)
        if node.value is None:
            raise InvalidLiteralException("Invalid literal for type 'bool'", node)


class AddressType(ValueType):
    __slots__ = ()
    _id = "address"
    _as_array = True
    _valid_literal = vy_ast.Hex

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
    _valid_literal = vy_ast.Hex

    def validate_literal(self, node):
        super().validate_literal(node)
        value = node.node_source_code
        if len(value) != 66:
            raise InvalidLiteralException("Invalid literal for type bytes32", node)


class Int128Type(IntegerType):
    __slots__ = ()
    _id = "int128"
    _invalid_op = ()

    def validate_literal(self, node):
        super().validate_literal(node)
        check_numeric_bounds("int128", node)


class Uint256Type(IntegerType):
    __slots__ = ()
    _id = "uint256"
    _invalid_op = vy_ast.USub

    def validate_literal(self, node):
        super().validate_literal(node)
        check_numeric_bounds("uint256", node)


class DecimalType(NumericType):
    __slots__ = ()
    _id = "decimal"
    _valid_literal = vy_ast.Decimal
    _invalid_op = vy_ast.Pow

    def validate_literal(self, node):
        super().validate_literal(node)
        value = Decimal(node.node_source_code)
        if value.quantize(Decimal('1.0000000000')) != value:
            raise InvalidLiteralException("Vyper supports a maximum of ten decimal points", node)
        check_numeric_bounds("int128", node)


class StringType(ArrayValueType):
    __slots__ = ()
    _id = "string"
    _valid_literal = vy_ast.Str


class BytesType(ArrayValueType):
    __slots__ = ()
    _id = "bytes"
    _valid_literal = (vy_ast.Bytes, vy_ast.Binary)

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
                f"Literal value exceeds the maximum length for {self}", node
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

    @classmethod
    def from_annotation(cls, namespace, node):
        self = cls(namespace)
        check_call_args(node, 2)
        self.key_type = datatypes.get_type_from_annotation(namespace, node.args[0])

        self.value_type = datatypes.get_type_from_annotation(namespace, node.args[1])
        return self

    def __repr__(self):
        return f"map({self.key_type}, {self.value_type})"

    def validate_literal(self, node):
        # TODO - direct assignment is always a no, but with a subscript is ++
        pass


# User-defined Types
# ------------------
#   These classes are used to represent custom data types that are implemented
#   within a contract, such as structs or contract interfaces.

class StructType(UserDefinedType):
    """
    Meta-type object for struct types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    members : OrderedDict
        A dictionary of {name: TypeObject} for each member of this meta-type.
    """

    __slots__ = ('members',)

    def __init__(self, namespace, node):
        super().__init__(namespace, node)
        self._id = node.name
        self.members = OrderedDict()
        for node in self.node.body:
            if not isinstance(node, vy_ast.AnnAssign):
                raise StructureException("Structs can only contain variables", node)
            if node.value is not None:
                raise StructureException("Cannot assign a value during struct declaration", node)
            member_name = node.target.id
            if member_name in self.members:
                raise StructureException(
                    f"Struct member '{member_name}'' has already been declared", node.target
                )
            self.members[member_name] = datatypes.get_type_from_annotation(
                namespace, node.annotation
            )

    def from_annotation(self, namespace, node):
        # TODO
        return self.__init__(self.namespace, self.node)

    def __repr__(self):
        return f"<Struct Type '{self._id}'>"


class InterfaceType(UserDefinedType):
    """
    Meta-type object for interface types.

    Attributes
    ----------
    _id : str
        Name of the custom type.
    node : ClassDef
        Vyper AST node that defines this meta-type.
    """
    __slots__ = ('_id', 'node', 'functions', 'address')
    _as_array = True

    def __init__(self, namespace, node):
        super().__init__(namespace, node)
        self._id = node.name
        self.functions = {}
        namespace = self.namespace.copy('builtin')
        if isinstance(self.node, vy_ast.Module):
            functions = self._get_module_functions(namespace)
        elif isinstance(self.node, vy_ast.ClassDef):
            functions = self._get_class_functions(namespace)
        else:
            raise
        for func in functions:
            if func.name in namespace or func.name in self.functions:
                raise StructureException("Namespace collision", func.node)
            self.functions[func.name] = func

    def _get_class_functions(self, namespace):
        functions = []
        for node in self.node.body:
            if not isinstance(node, vy_ast.FunctionDef):
                raise StructureException("Interfaces can only contain function definitions", node)
            functions.append(Function(namespace, node, "public"))
        return functions

    def _get_module_functions(self, namespace):
        functions = []
        for node in self.node.get_children({'ast_type': "FunctionDef"}):
            if "public" in node.decorator_list:
                functions.append(Function(namespace, node))
        return functions

    def validate_implements(self, namespace):
        unimplemented = [i.name for i in self.functions.values() if namespace.get(i.name) != i]
        if unimplemented:
            raise StructureException(
                f"Contract does not implement all interface functions: {', '.join(unimplemented)}",
                self.node
            )

    def from_annotation(self, namespace, node):
        obj = super().__init__(namespace, node)
        check_call_args(node, 1)
        address = node.args[0]
        if isinstance(address, vy_ast.Hex):
            obj.address = address.value
        elif isinstance(address, vy_ast.Name):
            obj.address = namespace[address.id]
            if not isinstance(obj.address, AddressType):
                raise
        else:
            raise
        # TODO validate address

    def validate_literal(self, node):
        # TODO
        pass
