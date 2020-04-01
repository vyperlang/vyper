
from decimal import (
    Decimal,
)
from typing import (
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context.types.bases.structure import (
    ArrayValueType,
    MemberType,
    ValueType,
)
from vyper.context.types.bases.data import (
    AddressBase,
    BoolBase,
    BytesBase,
    FixedBase,
    IntegerBase,
    StringBase,
)
from vyper.context.types.utils import (
    check_numeric_bounds,
)
from vyper.exceptions import (
    InvalidLiteral,
)
from vyper.utils import (
    checksum_encode,
)


class BoolType(BoolBase, ValueType):
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


class AddressType(AddressBase, MemberType, ValueType):
    __slots__ = ()
    _id = "address"
    _as_array = True
    _valid_literal = vy_ast.Hex
    _readonly_members = True
    _type_members = {
        'balance': "uint256",
        'codehash': "bytes32",
        'codesize': "int128",
        'is_contract': "bool",
    }

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


class Bytes32Type(BytesBase, ValueType):
    __slots__ = ()
    _id = "bytes32"
    _as_array = True
    _valid_literal = (vy_ast.Binary, vy_ast.Bytes, vy_ast.Hex)

    # included for compatibility with bytes array methods
    length = 32
    _length = 32
    _min_length = 32

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        if isinstance(node, vy_ast.Binary) and len(node.value) != 258:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        if isinstance(node, vy_ast.Bytes) and len(node.value.hex()) != 64:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        if isinstance(node, vy_ast.Hex) and len(node.value) != 66:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        return self


class Int128Type(IntegerBase, ValueType):
    __slots__ = ()
    _as_array = True
    _id = "int128"
    _invalid_op = ()
    _valid_literal = vy_ast.Int

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        check_numeric_bounds("int128", node)
        return self


class Uint256Type(IntegerBase, ValueType):
    __slots__ = ()
    _id = "uint256"
    _invalid_op = vy_ast.USub
    _as_array = True
    _valid_literal = vy_ast.Int

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        check_numeric_bounds("uint256", node)
        return self


class DecimalType(FixedBase, ValueType):
    __slots__ = ()
    _as_array = True
    _id = "decimal"
    _valid_literal = vy_ast.Decimal
    _invalid_op = vy_ast.Pow

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        self = super().from_literal(node)
        value = Decimal(node.value)
        if value.as_tuple().exponent < -10:
            raise InvalidLiteral("Vyper supports a maximum of ten decimal points", node)
        check_numeric_bounds("int128", node)
        return self


class StringType(StringBase, ArrayValueType):
    __slots__ = ()
    _id = "string"
    _valid_literal = vy_ast.Str


class BytesArrayType(BytesBase, ArrayValueType):
    __slots__ = ()
    _id = "bytes"
    _valid_literal = (vy_ast.Binary, vy_ast.Bytes, vy_ast.Hex)
