import pytest

from vyper.context.types.value.address import AddressPureType
from vyper.context.types.value.array_value import (
    BytesArrayPureType,
    StringPureType,
)
from vyper.context.types.value.boolean import BoolPureType
from vyper.context.types.value.bytes_fixed import Bytes32PureType
from vyper.context.types.value.numeric import (
    DecimalPureType,
    Int128PureType,
    Uint256PureType,
)
from vyper.exceptions import (
    InvalidLiteral,
    OverflowException,
    StructureException,
    UnexpectedNodeType,
    UnexpectedValue,
)

BASE_SOURCE = """
"Add a docstring so the target test node doesn't become one."
"""

PURE_TYPES = {
    AddressPureType: "address",
    BoolPureType: "bool",
    Bytes32PureType: "bytes32",
    BytesArrayPureType: "bytes[1]",
    DecimalPureType: "decimal",
    Int128PureType: "int128",
    StringPureType: "string[1]",
    Uint256PureType: "uint256",
}


VALID_LITERALS = {
    AddressPureType: ["0x6B175474E89094C44Da98b954EedeAC495271d0F"],
    BoolPureType: ["True", "False"],
    Bytes32PureType: ["0x6B175474E89094C44Da98b954EedeAC495271d0F4Da98b954EedeAC495271d0F"],
    BytesArrayPureType: [
        "b''",
        "b'this is thirty three bytes long!!'",
        r"b'\xbe\xef'",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F4Da98b954EedeAC495271d0F",
    ],
    DecimalPureType: ["-1.666", "3.31337", "8008135.0", "1.2345678901"],
    Int128PureType: ["-1", "0", "12", "42"],
    StringPureType: ["''", "'hello'", "'this is thirty three chars long!!'", "'-42'"],
    Uint256PureType: ["0", "12", "42"],
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
@pytest.mark.parametrize("PureType", VALID_LITERALS.keys())
def test_from_literal(build_node, PureType, source):
    node = build_node(source)

    if source in VALID_LITERALS[PureType]:
        obj = PureType.from_literal(node)
        assert isinstance(obj, PureType._type)
    else:
        with pytest.raises((InvalidLiteral, OverflowException)):
            PureType.from_literal(node)


@pytest.mark.parametrize("PureType,type_str", PURE_TYPES.items())
@pytest.mark.parametrize("source", INVALID_NODES + ["{}"])
def test_from_literal_invalid_node(build_node, PureType, type_str, source):
    source = source.format(type_str)
    node = build_node(source)

    with pytest.raises(UnexpectedNodeType):
        PureType.from_literal(node)


@pytest.mark.parametrize("PureType", VALID_LITERALS.keys())
@pytest.mark.parametrize(
    "source", [x for v in VALID_LITERALS.values() for x in v] + INVALID_LITERALS
)
def test_from_annotation_literal(build_node, PureType, source):
    node = build_node(source)

    with pytest.raises(StructureException):
        BoolPureType.from_annotation(node)


@pytest.mark.parametrize("PureType,type_str", PURE_TYPES.items())
@pytest.mark.parametrize("source", INVALID_NODES)
def test_from_annotation_invalid_structure(build_node, PureType, type_str, source):
    source = source.format(type_str)
    node = build_node(source)

    with pytest.raises((UnexpectedValue, StructureException)):
        PureType.from_annotation(node)


@pytest.mark.parametrize("PureType", PURE_TYPES.keys())
@pytest.mark.parametrize("type_str", PURE_TYPES.values())
def test_from_annotation_wrong_id(build_node, PureType, type_str):
    node = build_node(type_str)

    if type_str == PURE_TYPES[PureType]:
        obj = PureType.from_annotation(node)
        assert isinstance(obj, PureType._type)
    else:
        with pytest.raises((UnexpectedValue, StructureException)):
            PureType.from_annotation(node)
