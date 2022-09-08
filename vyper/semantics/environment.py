from typing import Dict

# TODO consolidate some of these imports
from vyper.semantics.types.user.struct import StructDefinition
from vyper.semantics.types.value.address import AddressDefinition
from vyper.semantics.types.value.array_value import BytesArrayDefinition
from vyper.semantics.types.value.bytes_fixed import Bytes32Definition
from vyper.semantics.types.value.numeric import Uint256Definition  # type: ignore

CONSTANT_ENVIRONMENT_VARS: Dict[str, Dict[str, type]] = {
    "block": {
        "coinbase": AddressDefinition,
        "difficulty": Uint256Definition,
        "prevrandao": Uint256Definition,
        "number": Uint256Definition,
        "gaslimit": Uint256Definition,
        "basefee": Uint256Definition,
        "prevhash": Bytes32Definition,
        "timestamp": Uint256Definition,
    },
    "chain": {"id": Uint256Definition},
    "msg": {
        "data": BytesArrayDefinition,
        "gas": Uint256Definition,
        "sender": AddressDefinition,
        "value": Uint256Definition,
    },
    "tx": {"origin": AddressDefinition, "gasprice": Uint256Definition},
}


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": AddressDefinition}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for name, members in CONSTANT_ENVIRONMENT_VARS.items():
        members = {k: v(is_constant=True) for k, v in members.items()}
        result[name] = StructDefinition(name, members, is_constant=True)

    return result


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: type_(is_constant=True) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
