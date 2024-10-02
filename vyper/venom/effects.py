from enum import Flag, auto


class Effects(Flag):
    STORAGE = auto()
    TRANSIENT = auto()
    MEMORY = auto()
    IMMUTABLES = auto()
    RETURNDATA = auto()
    BALANCE = auto()
    EXTCODE = auto()
    MSIZE = auto()


EMPTY = Effects(0)
ALL = ~EMPTY
STORAGE = Effects.STORAGE
TRANSIENT = Effects.TRANSIENT
MEMORY = Effects.MEMORY
IMMUTABLES = Effects.IMMUTABLES
RETURNDATA = Effects.RETURNDATA
BALANCE = Effects.BALANCE
EXTCODE = Effects.EXTCODE
MSIZE = Effects.MSIZE


_writes = {
    "sstore": STORAGE,
    "tstore": TRANSIENT,
    "mstore": MEMORY,
    "istore": IMMUTABLES,
    "call": ALL ^ IMMUTABLES,
    "delegatecall": ALL ^ IMMUTABLES,
    "staticcall": MEMORY | RETURNDATA,
    "create": ALL ^ (MEMORY | IMMUTABLES),
    "create2": ALL ^ (MEMORY | IMMUTABLES),
    "invoke": ALL,  # could be smarter, look up the effects of the invoked function
    "dloadbytes": MEMORY,
    "returndatacopy": MEMORY,
    "calldatacopy": MEMORY,
    "codecopy": MEMORY,
    "extcodecopy": MEMORY,
    "mcopy": MEMORY,
}

_reads = {
    "sload": STORAGE,
    "tload": TRANSIENT,
    "iload": IMMUTABLES,
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
    "log": MEMORY,
    "revert": MEMORY,
    "return": MEMORY,
    "sha3": MEMORY,
    "msize": MSIZE,
}

reads = _reads.copy()
writes = _writes.copy()

for k, v in reads.items():
    if MEMORY in v:
        if k not in writes:
            writes[k] = EMPTY
        writes[k] |= MSIZE

for k, v in writes.items():
    if MEMORY in v:
        writes[k] |= MSIZE
