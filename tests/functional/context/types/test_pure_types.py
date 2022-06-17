import pytest

from vyper.exceptions import (
    InvalidLiteral,
    OverflowException,
    StructureException,
    UnexpectedNodeType,
    UnexpectedValue,
)
from vyper.semantics.types.value.address import AddressPrimitive
from vyper.semantics.types.value.array_value import BytesArrayPrimitive, StringPrimitive
from vyper.semantics.types.value.boolean import BoolPrimitive
from vyper.semantics.types.value.bytes_fixed import Bytes32Primitive
from vyper.semantics.types.value.numeric import DecimalPrimitive, Int128Primitive, Uint256Primitive

BASE_SOURCE = """
"Add a docstring so the target test node doesn't become one."
"""

PRIMITIVES = {
    AddressPrimitive: "address",
    BoolPrimitive: "bool",
    Bytes32Primitive: "bytes32",
    BytesArrayPrimitive: "Bytes[1]",
    DecimalPrimitive: "decimal",
    Int128Primitive: "int128",
    StringPrimitive: "String[1]",
    Uint256Primitive: "uint256",
}


VALID_LITERALS = {
    AddressPrimitive: ["0x6B175474E89094C44Da98b954EedeAC495271d0F"],
    BoolPrimitive: ["True", "False"],
    Bytes32Primitive: [
        "0x6b175474e89094c44da98b954eedeac495271d0f4da98b954eedeac495271d0f",
        "0x6B175474E89094C44DA98B954EEDEAC495271D0F4DA98B954EEDEAC495271D0F",
    ],
    BytesArrayPrimitive: ["b''", "b'this is thirty three bytes long!!'", r"b'\xbe\xef'"],
    DecimalPrimitive: ["-1.666", "3.31337", "8008135.0", "1.2345678901"],
    Int128Primitive: ["-1", "0", "12", "42"],
    StringPrimitive: ["''", "'hello'", "'this is thirty three chars long!!'", "'-42'"],
    Uint256Primitive: ["0", "12", "42"],
}

INVALID_LITERALS = [
    "None",
    "115792089237316195423570985008687907853269984665640564039457584007913129639936",
    "115792089237316195423570985008687907853269984665640564039457584007913129639935.1",
]
INVALID_NODES = [
    "self.{}",
    "[{}]",
    "({},)",
    "{}()",
    "{}(foo)",
    "{}.foo",
    "public({})",
    "-{}",
    "{}[1]",
    "self.{}[1]",
]


# source is a combined list made from all lists in  VALID_LITERALS and INVALID_LITERALS
@pytest.mark.parametrize(
    "source", [x for v in VALID_LITERALS.values() for x in v] + INVALID_LITERALS
)
@pytest.mark.parametrize("Primitive", VALID_LITERALS.keys())
def test_from_literal(build_node, Primitive, source):
    node = build_node(source)

    if source in VALID_LITERALS[Primitive]:
        obj = Primitive.from_literal(node)
        assert isinstance(obj, Primitive._type)
    else:
        with pytest.raises((InvalidLiteral, OverflowException)):
            Primitive.from_literal(node)


@pytest.mark.parametrize("Primitive,type_str", PRIMITIVES.items())
@pytest.mark.parametrize("source", INVALID_NODES + ["{}"])
def test_from_literal_invalid_node(build_node, Primitive, type_str, source):
    source = source.format(type_str)
    node = build_node(source)

    with pytest.raises(UnexpectedNodeType):
        Primitive.from_literal(node)


@pytest.mark.parametrize("Primitive", VALID_LITERALS.keys())
@pytest.mark.parametrize(
    "source", [x for v in VALID_LITERALS.values() for x in v] + INVALID_LITERALS
)
def test_from_annotation_literal(build_node, Primitive, source):
    node = build_node(source)

    with pytest.raises(StructureException):
        BoolPrimitive.from_annotation(node)


@pytest.mark.parametrize("Primitive,type_str", PRIMITIVES.items())
@pytest.mark.parametrize("source", INVALID_NODES)
def test_from_annotation_invalid_structure(build_node, Primitive, type_str, source):
    source = source.format(type_str)
    node = build_node(source)

    with pytest.raises((UnexpectedValue, StructureException)):
        Primitive.from_annotation(node)


@pytest.mark.parametrize("Primitive", PRIMITIVES.keys())
@pytest.mark.parametrize("type_str", PRIMITIVES.values())
def test_from_annotation_wrong_id(build_node, Primitive, type_str):
    node = build_node(type_str)

    if type_str == PRIMITIVES[Primitive]:
        obj = Primitive.from_annotation(node)
        assert isinstance(obj, Primitive._type)
    else:
        with pytest.raises((UnexpectedValue, StructureException)):
            Primitive.from_annotation(node)
