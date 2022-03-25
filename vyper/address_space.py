from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class AddrSpace:
    """
    Object representing an "address space" (similar to the LLVM concept).
    It includes some information about the address space so that codegen
    can be written in a more generic way.
    """

    name: str
    wordsize: int
    load_op: str
    store_op: Optional[str]


# alternative:
# class Memory(AddrSpace):
#   @property
#   def wordsize(self):
#     return 32
# # implement more properties...
#
# MEMORY = Memory()

MEMORY = AddrSpace("memory", 32, "mload", "mstore")
STORAGE = AddrSpace("storage", 1, "sload", "sstore")
CALLDATA = AddrSpace("calldata", 32, "calldataload", None)
# immutables address space: "immutables" section of memory
# which is read-write in deploy code but then gets turned into
# the "data" section of the runtime code
IMMUTABLES = AddrSpace("immutables", 32, "iload", "istore")
# data addrspace: "data" section of runtime code, read-only.
DATA = AddrSpace("data", 32, "dload", None)
