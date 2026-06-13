from enum import Flag, auto
from typing import Optional

import vyper.evm.address_space as space


class Effects(Flag):
    STORAGE = auto()
    TRANSIENT = auto()
    MEMORY = auto()
    MSIZE = auto()
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
MSIZE = Effects.MSIZE
IMMUTABLES = Effects.IMMUTABLES
RETURNDATA = Effects.RETURNDATA
LOG = Effects.LOG
BALANCE = Effects.BALANCE
EXTCODE = Effects.EXTCODE
NON_MEMORY_EFFECTS = ~Effects.MEMORY
NON_STORAGE_EFFECTS = ~Effects.STORAGE
NON_TRANSIENT_EFFECTS = ~Effects.TRANSIENT

# MSIZE models the EVM memory high-water mark, which is observed by
# `memtop` (lowered to the MSIZE opcode). any memory access -- read or
# write -- can expand memory and therefore bump msize. memory expansion
# commutes (msize is monotonically non-decreasing), so memory-touching
# instructions can be freely reordered with each other as far as msize is
# concerned, but `memtop` must not cross any of them. we model this by
# making `memtop` *write* MSIZE and making instructions which read memory
# (without writing it) *read* MSIZE: this serializes `memtop` against
# memory reads in both directions while leaving the reads free to commute
# with each other. instructions which write MEMORY are already serialized
# against `memtop` through its MEMORY read effect.
_writes = {
    "memtop": MSIZE,
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
}

_reads = {
    "sload": STORAGE,
    "tload": TRANSIENT,
    "iload": IMMUTABLES | MEMORY | MSIZE,
    "mload": MEMORY | MSIZE,
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
    "log": MEMORY | MSIZE,
    "revert": MEMORY | MSIZE,
    "sha3": MEMORY | MSIZE,
    "return": MEMORY | MSIZE,
    "memtop": MEMORY,  # lowers to MSIZE; depends on all prior memory accesses
}

reads = _reads.copy()
writes = _writes.copy()
