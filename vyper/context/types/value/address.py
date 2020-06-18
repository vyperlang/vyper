from vyper import ast as vy_ast
from vyper.context.types.bases import BasePureType
from vyper.context.types.value.bases import MemberType
from vyper.context.types.value.boolean import BoolType
from vyper.context.types.value.bytes_fixed import Bytes32Type
from vyper.context.types.value.numeric import Int128Type, Uint256Type
from vyper.exceptions import InvalidLiteral
from vyper.utils import checksum_encode


class AddressType(MemberType):
    _id = "address"
    _type_members = {
        "balance": Uint256Type(is_constant=True),
        "codehash": Bytes32Type(is_constant=True),
        "codesize": Int128Type(is_constant=True),
        "is_contract": BoolType(is_constant=True),
    }


class AddressPureType(BasePureType):
    _id = "address"
    _type = AddressType
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
        return AddressType()
