import pytest

from vyper.exceptions import (
    InvalidLiteral,
    InvalidType,
    OverflowException,
    StructureException,
    UnexpectedNodeType,
)
from vyper.semantics.types import AddressT, BoolT, BytesT, DecimalT, StringT
from vyper.semantics.types.shortcuts import BYTES32_T, INT128_T, UINT256_T
from vyper.semantics.types.utils import type_from_annotation

BASE_SOURCE = """
"Add a docstring so the target test node doesn't become one."
"""

TYPES = {
    AddressT(): "address",
    BoolT(): "bool",
    BYTES32_T: "bytes32",
    DecimalT(): "decimal",
    INT128_T: "int128",
    UINT256_T: "uint256",
    BytesT: "Bytes[1]",
    StringT: "String[1]",
}

VALID_LITERALS = {
    AddressT(): ["0x6B175474E89094C44Da98b954EedeAC495271d0F"],
    BoolT(): ["True", "False"],
    BYTES32_T: [
        "0x6b175474e89094c44da98b954eedeac495271d0f4da98b954eedeac495271d0f",
        "0x6B175474E89094C44DA98B954EEDEAC495271D0F4DA98B954EEDEAC495271D0F",
    ],
    DecimalT(): ["-1.666", "3.31337", "8008135.0", "1.2345678901"],
    INT128_T: ["-1", "0", "12", "42"],
    UINT256_T: ["0", "12", "42"],
    BytesT: ["b''", "b'this is thirty three bytes long!!'", r"b'\xbe\xef'"],
    StringT: ["''", "'hello'", "'this is thirty three chars long!!'", "'-42'"],
}


INVALID_LITERALS = [
    "None",
    "115792089237316195423570985008687907853269984665640564039457584007913129639936",
    "115792089237316195423570985008687907853269984665640564039457584007913129639935.1",
]

ALL_LITERALS = [x for v in VALID_LITERALS.values() for x in v] + INVALID_LITERALS

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


def do_validate_node(type_, node):
    if type_ in (BytesT, StringT):
        t = type_.from_literal(node)
        t.validate_literal(node)
    else:
        type_.validate_literal(node)


@pytest.mark.parametrize("type_", TYPES.keys())
def test_valid_literals(build_node, type_):
    sources = VALID_LITERALS[type_]
    for source in sources:
        node = build_node(source)
        do_validate_node(type_, node)


@pytest.mark.parametrize("type_", TYPES.keys())
@pytest.mark.parametrize("source", INVALID_LITERALS)
def test_invalid_literals(build_node, type_, source):
    with pytest.raises((InvalidLiteral, OverflowException, UnexpectedNodeType)):
        # build_node throws; no need to run do_validate_node
        build_node(source)


@pytest.mark.parametrize("type_,type_str", TYPES.items())
@pytest.mark.parametrize("source", INVALID_NODES + ["{}"])
def test_invalid_node(build_node, type_, type_str, source):
    source = source.format(type_str)

    with pytest.raises((InvalidLiteral, UnexpectedNodeType)):
        node = build_node(source)
        do_validate_node(type_, node)


# no literal is a valid annotation
@pytest.mark.parametrize("type_", TYPES.keys())
@pytest.mark.parametrize("source", ALL_LITERALS)
def test_from_annotation_literal(build_node, type_, source):
    with pytest.raises((InvalidType, InvalidLiteral, OverflowException)):
        node = build_node(source)
        type_from_annotation(node)


def _check_type_equals(type_, t):
    if type_ in (BytesT, StringT):
        type_ = type_()
    if not type_.compare_type(t):
        raise InvalidType(f"{type_} != {t}")


@pytest.mark.parametrize("type_,type_str", TYPES.items())
@pytest.mark.parametrize("source", INVALID_NODES)
def test_invalid_annotations(build_node, type_, type_str, source):
    source = source.format(type_str)

    with pytest.raises((StructureException, InvalidType)):
        node = build_node(source)
        t = type_from_annotation(node)
        _check_type_equals(type_, t)


@pytest.mark.parametrize("type_", TYPES.keys())
@pytest.mark.parametrize("type_str", TYPES.values())
def test_from_annotation(build_node, type_, type_str):
    if type_str == TYPES[type_]:
        node = build_node(type_str)
        t = type_from_annotation(node)
        _check_type_equals(type_, t)
    else:
        with pytest.raises(InvalidType):
            node = build_node(type_str)
            t = type_from_annotation(node)
            _check_type_equals(type_, t)
