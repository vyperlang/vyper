
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
    InvalidLiteralException,
)
from vyper.utils import (
    checksum_encode,
)
from vyper.context.datatypes import (
    get_type_from_annotation,
)
from vyper.context.datatypes.bases import (
    ValueType,
    IntegerType,
    NumericType,
    ArrayValueType,
    CompoundType,
)


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
        self.key_type = get_type_from_annotation(namespace, node.args[0])

        self.value_type = get_type_from_annotation(namespace, node.args[1])
        return self

    def __repr__(self):
        return f"map({self.key_type}, {self.value_type})"

    def validate_literal(self, node):
        # TODO - direct assignment is always a no, but with a subscript is ++
        pass
