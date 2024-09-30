from enum import Flag, auto


class Effects(Flag):
    STORAGE = auto()
    TRANSIENT = auto()
    MEMORY = auto()
    IMMUTABLES = auto()
    BALANCE = auto()
    RETURNDATA = auto()


EMPTY = Effects(0)
ALL = ~EMPTY
STORAGE = Effects.STORAGE
TRANSIENT = Effects.TRANSIENT
MEMORY = Effects.MEMORY
IMMUTABLES = Effects.IMMUTABLES
BALANCE = Effects.BALANCE
RETURNDATA = Effects.RETURNDATA


writes = {
    "sstore": STORAGE,
    "tstore": TRANSIENT,
    "mstore": MEMORY,
    "istore": IMMUTABLES,
    "call": ALL,
    "delegatecall": ALL,
    "staticcall": MEMORY | RETURNDATA,
    "create": ALL,
    "create2": ALL,
    "invoke": ALL,  # could be smarter, look up the effects of the invoked function
    "dloadbytes": MEMORY,
    "returndatacopy": MEMORY,
    "calldatacopy": MEMORY,
    "codecopy": MEMORY,
    "extcodecopy": MEMORY,
    "mcopy": MEMORY,
}

reads = {
    "sload": STORAGE,
    "tload": TRANSIENT,
    "iload": IMMUTABLES,
    "mload": MEMORY,
    "mcopy": MEMORY,
    "call": ALL,
    "delegatecall": ALL,
    "staticcall": ALL,
    "returndatasize": RETURNDATA,
    "returndatacopy": RETURNDATA,
    "balance": BALANCE,
    "selfbalance": BALANCE,
    "log": MEMORY,
    "revert": MEMORY,
    "return": MEMORY,
    "sha3": MEMORY,
}
