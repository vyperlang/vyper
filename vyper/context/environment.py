from typing import Dict, Tuple

from vyper.context.types.meta.struct import StructDefinition
from vyper.context.types.value.address import AddressDefinition
from vyper.context.types.value.bytes_fixed import Bytes32Definition
from vyper.context.types.value.numeric import Uint256Definition

CONSTANT_ENVIRONMENT_VARS: Dict[str, Dict[str, type]] = {
    "block": {
        "coinbase": AddressDefinition,
        "difficulty": Uint256Definition,
        "number": Uint256Definition,
        "prevhash": Bytes32Definition,
        "timestamp": Uint256Definition,
    },
    "chain": {"id": Uint256Definition},
    "msg": {"gas": Uint256Definition, "sender": AddressDefinition, "value": Uint256Definition},
    "tx": {"origin": AddressDefinition},
}


MUTABLE_ENVIRONMENT_VARS: Dict[str, Tuple] = {
    "log": (StructDefinition, "log", {}),
    "self": (AddressDefinition,),
}


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
    result = {}
    for name, data in MUTABLE_ENVIRONMENT_VARS.items():
        obj, args = data[0], data[1:]
        result[name] = obj(*args, is_constant=True)
    return result
