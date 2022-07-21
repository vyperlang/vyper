from typing import Dict

from vyper.semantics.types import StructT, AddressT, BytesM_T, BytesT, IntegerT 
from vyper.semantics.types.primitives import UINT256_T, BYTES32_T

CONSTANT_ENVIRONMENT_VARS: Dict[str, Dict[str, type]] = {
    "block": {
        "coinbase": AddressT,
        "difficulty": UINT256_T,
        "number": UINT256_T,
        "gaslimit": UINT256_T,
        "basefee": UINT256_T,
        "prevhash": BYTES32_T,
        "timestamp": UINT256_T,
    },
    "chain": {"id": UINT256_T},
    "msg": {
        "data": BytesT,
        "gas": UINT256_T,
        "sender": AddressT,
        "value": UINT256_T,
    },
    "tx": {"origin": AddressT, "gasprice": UINT256_T},
}


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": AddressT()}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for name, members in CONSTANT_ENVIRONMENT_VARS.items():
        result[name] = StructT(name, members)

    return result


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: type_(is_constant=True) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
