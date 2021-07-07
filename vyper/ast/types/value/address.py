from vyper import ast as vy_ast
from vyper.ast.types.bases import BasePrimitive, MemberTypeDefinition
# TODO coalesce these imports
from vyper.ast.types.value.boolean import BoolDefinition
from vyper.ast.types.value.bytes_fixed import Bytes32Definition
from vyper.ast.types.value.numeric import Uint256Definition
from vyper.exceptions import CompilerPanic, InvalidLiteral
from vyper.utils import checksum_encode


class AddressDefinition(MemberTypeDefinition):
    _id = "address"
    _type_members = {
        "balance": Uint256Definition(is_immutable=True),
        "codehash": Bytes32Definition(is_immutable=True),
        "codesize": Uint256Definition(is_immutable=True),
        "is_contract": BoolDefinition(is_immutable=True),
    }


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
            raise InvalidLiteral("Invalid literal for type 'address'", node)
        if checksum_encode(addr) != addr:
            # this should have been caught in `vyper.ast.nodes.Hex.validate`
            raise CompilerPanic("Address checksum mismatch")
        return AddressDefinition()
