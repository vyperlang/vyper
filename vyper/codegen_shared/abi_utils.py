"""
Shared ABI encoding utilities used by both codegen pipelines.

If codegen_legacy is removed, consider moving these to vyper/abi.py
or into methods on VyperType / ABIType.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from vyper.semantics.types import VyperType

# In storage, dyn arrays use 1 slot for the length.
# In memory, dyn arrays use 32 bytes (1 word) for the length.
# (This constant is for storage; for memory, see context.py DYNAMIC_ARRAY_OVERHEAD_BYTES.)
DYNAMIC_ARRAY_OVERHEAD = 1


def is_tuple_like(typ: "VyperType") -> bool:
    """Check if type is tuple-like (tuple or struct)."""
    from vyper.semantics.types import StructT, TupleT

    # A lot of code paths treat tuples and structs similarly
    # so we have a convenience function to detect it
    ret = isinstance(typ, (TupleT, StructT))
    assert ret == hasattr(typ, "tuple_items")
    return ret


def needs_external_call_wrap(typ: "VyperType") -> bool:
    """
    For calls to ABI conforming contracts, return types are ALWAYS tuples
    even if only one element is being returned.
    https://docs.soliditylang.org/en/latest/abi-spec.html#function-selector-and-argument-encoding
    """
    from vyper.semantics.types import TupleT

    return not (isinstance(typ, TupleT) and typ.length > 1)


def calculate_type_for_external_return(typ: "VyperType") -> "VyperType":
    """Wrap type in a tuple if needed for ABI return encoding."""
    from vyper.semantics.types import TupleT

    if needs_external_call_wrap(typ):
        return TupleT([typ])
    return typ


def abi_encoding_matches_vyper(typ: "VyperType") -> bool:
    """
    Returns True if the ABI encoding matches vyper's memory encoding
    of a type, otherwise False.
    """
    return not typ.abi_type.is_dynamic()
