from typing import Dict

from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.types import AddressT, BytesT
from vyper.semantics.types.base import VyperType
from vyper.semantics.types.primitives import BYTES32_T, UINT256_T


class _Block(VyperType):
    _id = "block"
    _type_members = {
        "coinbase": AddressT(),
        "difficulty": UINT256_T,
        "prevrandao": UINT256_T,
        "number": UINT256_T,
        "gaslimit": UINT256_T,
        "basefee": UINT256_T,
        "prevhash": BYTES32_T,
        "timestamp": UINT256_T,
    }


class _Chain(VyperType):
    _id = "chain"
    _type_members = {"id": UINT256_T}


class _Msg(VyperType):
    _id = "msg"
    _type_members = {"data": BytesT(), "gas": UINT256_T, "sender": AddressT(), "value": UINT256_T}


class _Tx(VyperType):
    _id = "tx"
    _type_members = {"origin": AddressT(), "gasprice": UINT256_T}


CONSTANT_ENVIRONMENT_VARS = {t._id: t for t in (_Block(), _Chain(), _Tx(), _Msg())}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for k, v in CONSTANT_ENVIRONMENT_VARS.items():
        result[k] = VarInfo(v, is_constant=True)

    return result


# Not sure this is necessary, but add an ad-hoc type for `self` for clarity
class _SelfT(AddressT):
    pass


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": _SelfT}


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: VarInfo(type_()) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
