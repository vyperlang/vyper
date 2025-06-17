from dataclasses import dataclass
from typing import Optional

# TODO consider renaming this module to avoid confusion with the EVM
# concept of addresses (160-bit account IDs).


@dataclass(frozen=True)
class AddrSpace:
    """
    Object representing info about the "address space", analogous to the
    LLVM concept. It includes some metadata so that codegen can be
    written in a more generic way.

    Attributes:
        name: human-readable nickname for the address space
        word_scale: a constant which helps calculate offsets in a given
            address space. 1 for word-addressable locations (storage),
            32 for byte-addressable locations (memory, calldata, code)
        load_op: the opcode for loading a word from this address space
        store_op: the opcode for storing a word to this address space
            (an address space is read-only if store_op is None)
        copy_op: the opcode for batch-copying from this address space
            to memory
    """

    name: str
    word_scale: int
    load_op: str
    # TODO maybe make positional instead of defaulting to None
    store_op: Optional[str] = None
    copy_op: Optional[str] = None

    @property
    def word_addressable(self) -> bool:
        return self.word_scale == 1

    @property
    def has_copy_opcode(self):
        return self.copy_op is not None


# alternative:
# class Memory(AddrSpace):
#   @property
#   def word_scale(self):
#     return 32
# # implement more properties...
#
# MEMORY = Memory()

MEMORY = AddrSpace("memory", 32, "mload", "mstore", "mcopy")
STORAGE = AddrSpace("storage", 1, "sload", "sstore")
TRANSIENT = AddrSpace("transient", 1, "tload", "tstore")
CALLDATA = AddrSpace("calldata", 32, "calldataload", None, "calldatacopy")
# immutables address space: "immutables" section of memory
# which is read-write in deploy code but then gets turned into
# the "data" section of the runtime code
IMMUTABLES = AddrSpace("immutables", 32, "iload", "istore")
# data addrspace: "data" section of runtime code, read-only.
DATA = AddrSpace("data", 32, "dload", None, "dloadbytes")


def legal_in_staticcall(location: AddrSpace):
    return location not in (STORAGE, TRANSIENT)
