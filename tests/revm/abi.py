# wrapper module around whatever encoder we are using
from decimal import Decimal
from typing import Any

from eth.codecs.abi.decoder import Decoder
from eth.codecs.abi.encoder import Encoder
from eth.codecs.abi.exceptions import ABIError
from eth.codecs.abi.nodes import ABITypeNode, AddressNode, BytesNode, FixedNode
from eth.codecs.abi.parser import Parser
from hexbytes import HexBytes

_parsers: dict[str, ABITypeNode] = {}


class _Decoder(Decoder):
    @classmethod
    def visit_AddressNode(
        cls, node: AddressNode, value: bytes, checksum: bool = True, **kwargs: Any
    ) -> str | None:
        address = super().visit_AddressNode(node, value, checksum, **kwargs)
        return address if address != "0x0000000000000000000000000000000000000000" else None


class _Encoder(Encoder):
    """
    Custom encoder that converts some types to the expected format.
    """

    @classmethod
    def visit_BytesNode(cls, node: BytesNode, value: bytes | str) -> bytes:
        if isinstance(value, str):
            assert value.startswith("0x"), "Sanity check failed: expected hex string"
            value = bytes.fromhex(value[2:])
        return super().visit_BytesNode(node, value)

    @classmethod
    def visit_FixedNode(cls, node: FixedNode, value: Decimal | int) -> bytes:
        if isinstance(value, int):
            value = Decimal(value)
        return super().visit_FixedNode(node, value)

    @classmethod
    def visit_AddressNode(cls, node: AddressNode, value: str | HexBytes) -> bytes:
        if isinstance(value, HexBytes):
            value = value.hex()
        return super().visit_AddressNode(node, value)


def _get_parser(schema: str):
    try:
        return _parsers[schema]
    except KeyError:
        _parsers[schema] = (ret := Parser.parse(schema))
        return ret


def abi_encode(schema: str, data: Any) -> bytes:
    return _Encoder.encode(_get_parser(schema), data)


def abi_decode(schema: str, data: bytes) -> Any:
    return _Decoder.decode(_get_parser(schema), data)


def is_abi_encodable(abi_type: str, data: Any) -> bool:
    try:
        abi_encode(abi_type, data)
        return True
    except ABIError:
        return False
