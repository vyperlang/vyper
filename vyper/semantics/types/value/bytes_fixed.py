from vyper import ast as vy_ast
from vyper.exceptions import InvalidLiteral
from vyper.semantics.types.abstract import BytesAbstractType
from vyper.semantics.types.bases import BasePrimitive, BaseTypeDefinition, ValueTypeDefinition


class Bytes4Definition(BytesAbstractType, ValueTypeDefinition):

    # included for compatibility with bytes array methods
    _id = "bytes4"
    length = 4
    _length = 4
    _min_length = 4


class Bytes4Primitive(BasePrimitive):

    _as_array = True
    _type = Bytes4Definition
    _id = "bytes4"
    _valid_literal = (vy_ast.Bytes, vy_ast.Hex)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> BaseTypeDefinition:
        obj = super().from_literal(node)
        if isinstance(node, vy_ast.Bytes) and len(node.value.hex()) != 8:
            raise InvalidLiteral("Invalid literal for type bytes4", node)
        if isinstance(node, vy_ast.Hex) and len(node.value) != 10:
            raise InvalidLiteral("Invalid literal for type bytes4", node)
        return obj


class Bytes32Definition(BytesAbstractType, ValueTypeDefinition):

    # included for compatibility with bytes array methods
    _id = "bytes32"
    length = 32
    _length = 32
    _min_length = 32


class Bytes32Primitive(BasePrimitive):

    _as_array = True
    _type = Bytes32Definition
    _id = "bytes32"
    _valid_literal = (vy_ast.Bytes, vy_ast.Hex)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> BaseTypeDefinition:
        obj = super().from_literal(node)
        if isinstance(node, vy_ast.Bytes) and len(node.value.hex()) != 64:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        if isinstance(node, vy_ast.Hex) and len(node.value) != 66:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        return obj
