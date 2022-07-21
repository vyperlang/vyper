from typing import Dict

from vyper.semantics.types import StructT, AddressT, BytesM_T, BytesT, IntegerT 
from vyper.semantics.types.primitives import T_UINT256, T_BYTES32

CONSTANT_ENVIRONMENT_VARS: Dict[str, Dict[str, type]] = {
    "block": {
        "coinbase": AddressT,
        "difficulty": T_UINT256,
        "number": T_UINT256,
        "gaslimit": T_UINT256,
        "basefee": T_UINT256,
        "prevhash": T_BYTES32,
        "timestamp": T_UINT256,
    },
    "chain": {"id": T_UINT256},
    "msg": {
        "data": BytesT,
        "gas": T_UINT256,
        "sender": AddressT,
        "value": T_UINT256,
    },
    "tx": {"origin": AddressT, "gasprice": T_UINT256},
}


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": AddressT}


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
