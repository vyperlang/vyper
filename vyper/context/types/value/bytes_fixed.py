from vyper import ast as vy_ast
from vyper.context.types.bases import AbstractDataType, BasePureType
from vyper.context.types.value.bases import ValueType
from vyper.exceptions import InvalidLiteral


class BytesBase(AbstractDataType):

    """Abstract data class for bytes types (bytes32, bytes[])."""

    def __repr__(self):
        return "bytes"


class Bytes32Type(BytesBase, ValueType):

    # included for compatibility with bytes array methods
    _id = "bytes32"
    length = 32
    _length = 32
    _min_length = 32


class Bytes32Pure(BasePureType):

    _as_array = True
    _type = Bytes32Type
    _id = "bytes32"
    _valid_literal = (vy_ast.Bytes, vy_ast.Hex)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        obj = super().from_literal(node)
        if isinstance(node, vy_ast.Bytes) and len(node.value.hex()) != 64:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        if isinstance(node, vy_ast.Hex) and len(node.value) != 66:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        return obj
