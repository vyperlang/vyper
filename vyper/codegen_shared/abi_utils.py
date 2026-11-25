"""
Shared ABI encoding utilities used by both codegen pipelines.

If codegen_legacy is removed, consider moving these to vyper/abi.py
or into methods on VyperType / ABIType.
"""

from vyper.semantics.types import StructT, TupleT


def is_tuple_like(typ):
    # A lot of code paths treat tuples and structs similarly
    # so we have a convenience function to detect it
    ret = isinstance(typ, (TupleT, StructT))
    assert ret == hasattr(typ, "tuple_items")
    return ret


def needs_external_call_wrap(typ):
    # for calls to ABI conforming contracts.
    # according to the ABI spec, return types are ALWAYS tuples even
    # if only one element is being returned.
    # https://solidity.readthedocs.io/en/latest/abi-spec.html#function-selector-and-argument-encoding
    # "and the return values v_1, ..., v_k of f are encoded as
    #
    #    enc((v_1, ..., v_k))
    #    i.e. the values are combined into a tuple and encoded.
    # "
    # therefore, wrap it in a tuple if it's not already a tuple.
    # for example, `bytes` is returned as abi-encoded (bytes,)
    # and `(bytes,)` is returned as abi-encoded ((bytes,),)
    # In general `-> X` gets returned as (X,)
    # including structs. MyStruct is returned as abi-encoded (MyStruct,).
    # (Sorry this is so confusing. I didn't make these rules.)

    return not (isinstance(typ, TupleT) and typ.length > 1)


def calculate_type_for_external_return(typ):
    if needs_external_call_wrap(typ):
        return TupleT([typ])
    return typ


def abi_encoding_matches_vyper(typ):
    """
    returns True if the ABI encoding matches vyper's memory encoding of
    a type, otherwise False
    """
    return not typ.abi_type.is_dynamic()
