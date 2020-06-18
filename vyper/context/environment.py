from typing import Dict

from vyper.context.types.meta.struct import StructType
from vyper.context.types.value.address import AddressType
from vyper.context.types.value.bytes_fixed import Bytes32Type
from vyper.context.types.value.numeric import Uint256Type

CONSTANT_ENVIRONMENT_VARS = {
    "block": {
        "coinbase": AddressType,
        "difficulty": Uint256Type,
        "number": Uint256Type,
        "prevhash": Bytes32Type,
        "timestamp": Uint256Type,
    },
    "chain": {"id": Uint256Type},
    "msg": {"gas": Uint256Type, "sender": AddressType, "value": Uint256Type},
    "tx": {"origin": AddressType},
}


MUTABLE_ENVIRONMENT_VARS = {
    "log": (StructType, "log", {}),
    "self": (AddressType,),
}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for name, members in CONSTANT_ENVIRONMENT_VARS.items():
        members = {k: v(is_constant=True) for k, v in members.items()}
        result[name] = StructType(name, members, is_constant=True)

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
