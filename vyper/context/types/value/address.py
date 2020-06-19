from vyper import ast as vy_ast
from vyper.context.types.bases import BasePureType, MemberTypeDefinition
from vyper.context.types.value.boolean import BoolDefinition
from vyper.context.types.value.bytes_fixed import Bytes32Definition
from vyper.context.types.value.numeric import (
    Int128Definition,
    Uint256Definition,
)
from vyper.exceptions import InvalidLiteral
from vyper.utils import checksum_encode


class AddressDefinition(MemberTypeDefinition):
    _id = "address"
    _type_members = {
        "balance": Uint256Definition(is_constant=True),
        "codehash": Bytes32Definition(is_constant=True),
        "codesize": Int128Definition(is_constant=True),
        "is_contract": BoolDefinition(is_constant=True),
    }


class AddressPureType(BasePureType):
    _id = "address"
    _type = AddressDefinition
    _as_array = True
    _valid_literal = vy_ast.Hex

    @classmethod
    def from_literal(cls, node: vy_ast.Constant):
        super().from_literal(node)
        addr = node.value
        if len(addr) != 42:
            raise InvalidLiteral("Invalid literal for type 'address'", node)
        if checksum_encode(addr) != addr:
            raise InvalidLiteral(
                "Address checksum mismatch. If you are sure this is the right "
                f"address, the correct checksummed form is: {checksum_encode(addr)}",
                node,
            )
        return AddressDefinition()
