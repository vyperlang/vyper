
from decimal import (
    Decimal,
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
from vyper.context.types.bases import (
    ArrayValueType,
    BytesType,
    CompoundType,
    IntegerType,
    MemberType,
    NumericType,
    ValueType,
)
from vyper.context.types.utils import (
    check_numeric_bounds,
    compare_types,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.context.utils import (
    validate_call_args,
)
from vyper.exceptions import (
    InvalidLiteral,
)
from vyper.utils import (
    checksum_encode,
)


class BoolType(ValueType):
    __slots__ = ()
    _id = "bool"
    _as_array = True
    _valid_literal = vy_ast.NameConstant

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        if node.value is None:
            raise InvalidLiteral("Invalid literal for type 'bool'", node)
        return super().from_literal(node)

    def validate_boolean_op(self, node: vy_ast.BoolOp):
        return

    def validate_numeric_op(self, node: Union[vy_ast.UnaryOp, vy_ast.BinOp]):
        if isinstance(node.op, vy_ast.Not):
            return
        super().validate_numeric_op(node)


class AddressType(MemberType, ValueType):
    __slots__ = ()
    _id = "address"
    _as_array = True
    _valid_literal = vy_ast.Hex
    _readonly_members = True

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        addr = node.value
        if len(addr) != 42:
            raise InvalidLiteral("Invalid literal for type 'address'", node)
        if checksum_encode(addr) != addr:
            raise InvalidLiteral(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node
            )
        return self

    # TODO move this to init, avoid initializing types in namespace
    def get_member_type(self, node: vy_ast.Attribute):
        if 'balance' not in self.members:
            members = {
                'balance': type(namespace['uint256'])("wei"),
                'codehash': type(namespace['bytes32'])(),
                'codesize': type(namespace['int128'])(),
                'is_contract': type(namespace['bool'])()
            }
            self.add_member_types(**members)

        return super().get_member_type(node)


class Bytes32Type(BytesType):
    __slots__ = ()
    _id = "bytes32"
    _as_array = True
    _valid_literal = vy_ast.Hex

    # included for compatibility with bytes array methods
    length = 32
    min_length = 32

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        if len(node.value) != 66:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        return self


class Int128Type(IntegerType):
    __slots__ = ()
    _id = "int128"
    _invalid_op = ()

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        check_numeric_bounds("int128", node)
        return self


class Uint256Type(IntegerType):
    __slots__ = ()
    _id = "uint256"
    _invalid_op = vy_ast.USub

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        check_numeric_bounds("uint256", node)
        return self


class DecimalType(NumericType):
    __slots__ = ()
    _id = "decimal"
    _valid_literal = vy_ast.Decimal
    _invalid_op = vy_ast.Pow

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        value = Decimal(node.value)
        if value.quantize(Decimal('1.0000000000')) != value:
            raise InvalidLiteral("Vyper supports a maximum of ten decimal points", node)
        check_numeric_bounds("int128", node)
        return self


class StringType(ArrayValueType):
    __slots__ = ()
    _id = "string"
    _valid_literal = vy_ast.Str


class BytesArrayType(BytesType, ArrayValueType):
    __slots__ = ()
    _id = "bytes"
    _valid_literal = (vy_ast.Bytes, vy_ast.Binary)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        if not isinstance(node, vy_ast.Binary):
            return super().from_literal(node)

        value = node.value
        mod = (len(value)-2) % 8
        if mod:
            raise InvalidLiteral(
                f"Bit notation requires a multiple of 8 bits. {8-mod} bit(s) are missing.", node
            )
        self = cls()
        self.min_length = (len(value)-2) // 8
        return self


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

    def _compare_type(self, other):
        return (
            super()._compare_type(other) and
            self.key_type == other.key_type and
            self.value_type == other.value_type
        )

    @classmethod
    def from_annotation(cls, node: vy_ast.VyperNode):
        self = cls()
        validate_call_args(node, 2)
        self.key_type = get_type_from_annotation(node.args[0])

        self.value_type = get_type_from_annotation(node.args[1])
        return self

    def __repr__(self):
        return f"map({self.key_type}, {self.value_type})"

    def get_index_type(self, node: vy_ast.VyperNode):
        idx_type = get_type_from_node(node)
        compare_types(self.key_type, idx_type, node)
        return self.value_type
