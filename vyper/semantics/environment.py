from typing import Dict

from vyper.semantics.analysis.base import Modifiability, VarInfo
from vyper.semantics.types import AddressT, BytesT, SelfT, VyperType
from vyper.semantics.types.shortcuts import BYTES32_T, UINT256_T


# common properties for environment variables
class _EnvType(VyperType):
    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return hash(id(self))


class _Block(_EnvType):
    _id = "block"
    _type_members = {
        "coinbase": AddressT(),
        "difficulty": UINT256_T,
        "prevrandao": BYTES32_T,
        "number": UINT256_T,
        "gaslimit": UINT256_T,
        "basefee": UINT256_T,
        "blobbasefee": UINT256_T,
        "prevhash": BYTES32_T,
        "timestamp": UINT256_T,
    }


class _Chain(_EnvType):
    _id = "chain"
    _type_members = {"id": UINT256_T}


class _Msg(_EnvType):
    _id = "msg"
    _type_members = {
        "data": BytesT(),
        "gas": UINT256_T,
        "mana": UINT256_T,
        "sender": AddressT(),
        "value": UINT256_T,
    }


class _Tx(_EnvType):
    _id = "tx"
    _type_members = {"origin": AddressT(), "gasprice": UINT256_T}


CONSTANT_ENVIRONMENT_VARS = {t._id: t for t in (_Block(), _Chain(), _Tx(), _Msg())}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    result = {}
    for k, v in CONSTANT_ENVIRONMENT_VARS.items():
        result[k] = VarInfo(v, modifiability=Modifiability.RUNTIME_CONSTANT)

    return result


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": SelfT}


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: VarInfo(type_()) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
