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

    def __init__(self):
        # construct members in __init__ (not class-level _type_members)
        # so each instance gets a fresh BytesT().  compare_type() mutates
        # BytesT._length as a side effect; a class-level singleton would
        # leak that mutation across compilations and function analyses.
        # TODO: replace with _type_members once compare_type no longer mutates
        # types.
        super().__init__(
            {
                "data": BytesT(),
                "gas": UINT256_T,
                "mana": UINT256_T,
                "sender": AddressT(),
                "value": UINT256_T,
            }
        )


class _Tx(_EnvType):
    _id = "tx"
    _type_members = {"origin": AddressT(), "gasprice": UINT256_T}


_CONSTANT_ENV_TYPES: tuple[type[_EnvType], ...] = (_Block, _Chain, _Tx, _Msg)

CONSTANT_ENVIRONMENT_VARS = {cls._id for cls in _CONSTANT_ENV_TYPES}


def get_constant_vars() -> Dict:
    """
    Get a dictionary of constant environment variables.

    Returns fresh instances each call — compare_type() has side effects
    that mutate BytesT()._length, so env types (especially _Msg.data)
    must not be shared across compilations or function analyses.
    TODO: fix compare_type to not have side effects, then this can
    return singletons again.
    """
    return {
        t._id: VarInfo(t, modifiability=Modifiability.RUNTIME_CONSTANT)
        for t in (cls() for cls in _CONSTANT_ENV_TYPES)
    }


MUTABLE_ENVIRONMENT_VARS: Dict[str, type[VyperType]] = {"self": SelfT}


def get_mutable_vars() -> Dict:
    """
    Get a dictionary of mutable environment variables (those that are
    modified during the course of contract execution, such as `self`).
    """
    return {name: VarInfo(type_()) for name, type_ in MUTABLE_ENVIRONMENT_VARS.items()}
