_ALL = ("storage", "transient", "memory", "immutables", "balance", "returndata")

_writes = {
    "sstore": "storage",
    "tstore": "transient",
    "mstore": "memory",
    "istore": "immutables",
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": "memory",
    "create": _ALL,
    "create2": _ALL,
    "invoke": _ALL,  # could be smarter, look up the effects of the invoked function
    "dloadbytes": "memory",
    "returndatacopy": "memory",
    "calldatacopy": "memory",
    "codecopy": "memory",
    "extcodecopy": "memory",
    "mcopy": "memory",
}
_reads = {
    "sload": "storage",
    "tload": "transient",
    "iload": "immutables",
    "mload": "memory",
    "mcopy": "memory",
    "call": _ALL,
    "delegatecall": _ALL,
    "staticcall": _ALL,
    "returndatasize": "returndata",
    "returndatacopy": "returndata",
    "balance": "balance",
    "selfbalance": "balance",
    "log": "memory",
    "revert": "memory",
    "return": "memory",
    "sha3": "memory",
}


def _mktuple(x):
    if not isinstance(x, tuple):
        x = (x,)
    return x


writes = {k: _mktuple(v) for k, v in _writes.items()}
reads = {k: _mktuple(v) for k, v in _reads.items()}
