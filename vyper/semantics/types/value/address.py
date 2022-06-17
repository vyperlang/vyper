from vyper import ast as vy_ast
from vyper.abi_types import ABI_Address, ABIType
from vyper.exceptions import InvalidLiteral
from vyper.utils import checksum_encode, is_checksum_encoded

from ..bases import BasePrimitive, MemberTypeDefinition, ValueTypeDefinition
from .array_value import BytesArrayDefinition
from .boolean import BoolDefinition
from .bytes_fixed import Bytes32Definition
from .numeric import Uint256Definition  # type: ignore


class AddressDefinition(MemberTypeDefinition, ValueTypeDefinition):
    _id = "address"
    _type_members = {
        "balance": Uint256Definition(is_constant=True),
        "codehash": Bytes32Definition(is_constant=True),
        "codesize": Uint256Definition(is_constant=True),
        "is_contract": BoolDefinition(is_constant=True),
        "code": BytesArrayDefinition(is_constant=True),
    }

    @property
    def abi_type(self) -> ABIType:
        return ABI_Address()


class AddressPrimitive(BasePrimitive):
    _as_array = True
    _id = "address"
    _type = AddressDefinition
    _valid_literal = (vy_ast.Hex,)

    @classmethod
    def from_literal(cls, node: vy_ast.Constant) -> AddressDefinition:
        super().from_literal(node)
        addr = node.value
        if len(addr) != 42:
            n_bytes = (len(addr) - 2) // 2
            raise InvalidLiteral(f"Invalid address. Expected 20 bytes, got {n_bytes}.", node)

        if not is_checksum_encoded(addr):
            raise InvalidLiteral(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node,
            )

        return AddressDefinition()
