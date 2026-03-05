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


_CONSTANT_ENV_TYPES = (_Block, _Chain, _Tx, _Msg)

CONSTANT_ENVIRONMENT_VARS = {cls._id for cls in _CONSTANT_ENV_TYPES}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.
    """
    # create fresh instances each call to avoid mutable singleton pollution
    # (BytesT() in _Msg gets mutated by compare_type side effects)
    return {
        t._id: VarInfo(t, modifiability=Modifiability.RUNTIME_CONSTANT)
        for t in (cls() for cls in _CONSTANT_ENV_TYPES)
    }


MUTABLE_ENVIRONMENT_VARS: Dict[str, type] = {"self": SelfT}


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: VarInfo(type_()) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
