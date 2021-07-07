from typing import Dict

# TODO should these be relative imports
from vyper.ast.types.meta.struct import StructDefinition
from vyper.ast.types.value.address import AddressDefinition
from vyper.ast.types.value.array_value import BytesArrayDefinition
from vyper.ast.types.value.bytes_fixed import Bytes32Definition
from vyper.ast.types.value.numeric import Uint256Definition

CONSTANT_ENVIRONMENT_VARS: Dict[str, Dict[str, type]] = {
    "block": {
        "coinbase": AddressDefinition,
        "difficulty": Uint256Definition,
        "number": Uint256Definition,
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
    "tx": {"origin": AddressDefinition},
}


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {
    "self": AddressDefinition,
}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for name, members in CONSTANT_ENVIRONMENT_VARS.items():
        members = {k: v(is_immutable=True) for k, v in members.items()}
        result[name] = StructDefinition(name, members, is_immutable=True)

    return result


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    result = {}
    for name, type_ in MUTABLE_ENVIRONMENT_VARS.items():
        result[name] = type_(is_immutable=True)

    return result
