from enum import Flag, auto


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
NON_MEMORY_EFFECTS = ~(Effects.MEMORY | Effects.MSIZE)
NON_STORAGE_EFFECTS = ~Effects.STORAGE
NON_TRANSIENT_EFFECTS = ~Effects.TRANSIENT

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
    "extcodesize": EXTCODE,
    "extcodehash": EXTCODE,
    "selfdestruct": BALANCE,  # may modify code, but after the transaction
    "log": MEMORY,
    "revert": MEMORY,
    "sha3": MEMORY,
    "sha3_64": MEMORY,
    "msize": MSIZE,
    "return": MEMORY,
}

reads = _reads.copy()
writes = _writes.copy()

for k, v in reads.items():
    if MEMORY in v or IMMUTABLES in v:
        if k not in writes:
            writes[k] = EMPTY
        writes[k] |= MSIZE

for k, v in writes.items():
    if MEMORY in v or IMMUTABLES in v:
        writes[k] |= MSIZE
