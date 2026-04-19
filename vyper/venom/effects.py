from enum import Flag, auto
from typing import Optional

import vyper.evm.address_space as space


class Effects(Flag):
    STORAGE = auto()
    TRANSIENT = auto()
    MEMORY = auto()
    MEMORY_SIZE = auto()
    IMMUTABLES = auto()
    RETURNDATA = auto()
    LOG = auto()
    BALANCE = auto()
    EXTCODE = auto()


def to_addr_space(eff: Effects) -> Optional[space.AddrSpace]:
    translate = {
        MEMORY: space.MEMORY,
        STORAGE: space.STORAGE,
        TRANSIENT: space.TRANSIENT,
        IMMUTABLES: space.IMMUTABLES,
    }
    return translate.get(eff, None)


EMPTY = Effects(0)
ALL = ~EMPTY
STORAGE = Effects.STORAGE
TRANSIENT = Effects.TRANSIENT
MEMORY = Effects.MEMORY
MEMORY_SIZE = Effects.MEMORY_SIZE
IMMUTABLES = Effects.IMMUTABLES
RETURNDATA = Effects.RETURNDATA
LOG = Effects.LOG
BALANCE = Effects.BALANCE
EXTCODE = Effects.EXTCODE
NON_MEMORY_EFFECTS = ~(Effects.MEMORY | Effects.MEMORY_SIZE)
NON_STORAGE_EFFECTS = ~Effects.STORAGE
NON_TRANSIENT_EFFECTS = ~Effects.TRANSIENT

_writes = {
    "sstore": STORAGE,
    "tstore": TRANSIENT,
    "mstore": MEMORY,
    "istore": IMMUTABLES | MEMORY,
    "call": ALL ^ IMMUTABLES,
    "delegatecall": ALL ^ IMMUTABLES,
    "staticcall": MEMORY | RETURNDATA,
    "create": ALL ^ (MEMORY | IMMUTABLES),
    "create2": ALL ^ (MEMORY | IMMUTABLES),
    "invoke": ALL,  # could be smarter, look up the effects of the invoked function
    "log": LOG,
    "dloadbytes": MEMORY,
    "dload": MEMORY,
    "returndatacopy": MEMORY,
    "calldatacopy": MEMORY,
    "codecopy": MEMORY,
    "extcodecopy": MEMORY,
    "mcopy": MEMORY,
    "dalloca": MEMORY,  # bumps the free memory pointer at the FMP slot
}

_reads = {
    "sload": STORAGE,
    "tload": TRANSIENT,
    "iload": IMMUTABLES | MEMORY,
    "mload": MEMORY,
    "mcopy": MEMORY,
    "call": ALL,
    "delegatecall": ALL,
    "staticcall": ALL,
    "create": ALL,
    "create2": ALL,
    "invoke": ALL,
    "returndatasize": RETURNDATA,
    "returndatacopy": RETURNDATA,
    "balance": BALANCE,
    "selfbalance": BALANCE,
    "extcodecopy": EXTCODE,
    "extcodesize": EXTCODE,
    "extcodehash": EXTCODE,
    "selfdestruct": BALANCE,  # may modify code, but after the transaction
    "log": MEMORY,
    "revert": MEMORY,
    "sha3": MEMORY,
    "return": MEMORY,
    "memtop": MEMORY | MEMORY_SIZE,  # lowers to MSIZE; depends on memory growth
    "dalloca": MEMORY,  # reads the FMP slot to return the current pointer
}

reads = _reads.copy()
writes = _writes.copy()
