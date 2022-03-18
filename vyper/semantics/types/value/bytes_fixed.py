from vyper import ast as vy_ast
from vyper.abi_types import ABI_BytesM, ABIType
from vyper.exceptions import InvalidLiteral
from vyper.semantics.types.abstract import BytesMAbstractType
from vyper.semantics.types.bases import BasePrimitive, BaseTypeDefinition, ValueTypeDefinition


class BytesMDefinition(BytesMAbstractType, ValueTypeDefinition):
    length: int

    @property
    def _id(self):
        return f"bytes{self.length}"

    @property
    def abi_type(self) -> ABIType:
        return ABI_BytesM(self.length)


class BytesMPrimitive(BasePrimitive):
    _length: int

    _as_array = True
    _valid_literal = (vy_ast.Bytes, vy_ast.Hex)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> BaseTypeDefinition:
        if isinstance(node, vy_ast.Bytes) and len(node.value) != cls._length:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        if isinstance(node, vy_ast.Hex) and len(node.value) != 2 + 2 * cls._length:
            raise InvalidLiteral("Invalid literal for type bytes32", node)
        obj = super().from_literal(node)
        return obj


# including so mypy does not complain while we are generating types dynamically
class Bytes32Definition(BytesMDefinition):

    # included for compatibility with bytes array methods
    length = 32
    _length = 32
    _min_length = 32


class Bytes32Primitive(BytesMPrimitive):
    _type = Bytes32Definition
    _length = 32
    _id = "bytes32"


for i in range(31):
    m = i + 1
    definition = type(
        f"Bytes{m}Definition", (BytesMDefinition,), {"length": m, "_length": m, "_min_length": m}
    )
    prim = type(
        f"Bytes{m}Primitive",
        (BytesMPrimitive,),
        {"_length": m, "_type": definition, "_id": f"bytes{m}"},
    )

    globals()[f"Bytes{m}Definition"] = definition
    globals()[f"Bytes{m}Primitive"] = prim
