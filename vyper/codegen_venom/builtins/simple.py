"""
Simple built-in functions: len, empty, min, max, abs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from vyper.codegen_venom.builtins._call import BuiltinLowerer, PreparedBuiltinCall
from vyper.codegen_venom.call_args import DataViewKind, length_source
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import DArrayT
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_len(call: PreparedBuiltinCall) -> IROperand:
    """
    len(x) for dynamic arrays, bytes, strings.

    Returns the length stored at the pointer (first word).
    Special case: len(msg.data) returns calldatasize.
    """
    return call.word("b")


def lower_empty(call: PreparedBuiltinCall) -> Union[IROperand, VyperValue]:
    """
    empty(T) returns zero-initialized value of type T.

    For primitives: returns 0
    For complex types: allocates memory and zeros it

    Note: alloca reserves memory but doesn't guarantee it's zeroed (may reuse
    memory from earlier in the function). We must explicitly zero the buffer.
    For bytestrings/dynarrays, zeroing the length word (first 32 bytes) is
    sufficient since length=0 means no valid data. For other complex types,
    we zero the entire buffer.
    """
    ctx = call.ctx
    typ = call.return_type

    if typ._is_prim_word:
        return IRLiteral(0)
    else:
        # Allocate memory buffer
        val = ctx.new_temporary_value(typ)
        assert isinstance(val.operand, IRVariable)

        # Explicitly zero the memory buffer
        # For bytestrings/dynarrays, just zero the length word (first 32 bytes)
        # since length=0 means no valid data
        if isinstance(typ, (_BytestringT, DArrayT)):
            ctx.builder.mstore(val.operand, IRLiteral(0))
        else:
            # For other complex types, zero the entire buffer
            _zero_memory(ctx, val.operand, typ.memory_bytes_required)

        return val


def _zero_memory(ctx: VenomCodegenContext, ptr: IRVariable, size: int) -> None:
    """Zero out a memory region by writing zeros word by word."""
    for offset in range(0, size, 32):
        dst = ctx.builder.add(ptr, IRLiteral(offset))
        ctx.builder.mstore(dst, IRLiteral(0))


def lower_min(call: PreparedBuiltinCall) -> IROperand:
    """min(a, b) - returns smaller of two values."""
    return _lower_minmax(call, is_max=False)


def lower_max(call: PreparedBuiltinCall) -> IROperand:
    """max(a, b) - returns larger of two values."""
    return _lower_minmax(call, is_max=True)


def _lower_minmax(call: PreparedBuiltinCall, is_max: bool) -> IROperand:
    """
    Common implementation for min/max.

    Uses select: if (a op b) then a else b
    """
    ctx = call.ctx
    b = ctx.builder

    a_val = call.word("a")
    b_val = call.word("b")
    typ = call.arg_type(0)

    # Choose comparison - signed for most types, unsigned only for uint256
    if typ == UINT256_T:
        cmp_result = b.gt(a_val, b_val) if is_max else b.lt(a_val, b_val)
    else:
        cmp_result = b.sgt(a_val, b_val) if is_max else b.slt(a_val, b_val)

    return b.select(cmp_result, a_val, b_val)


def lower_abs(call: PreparedBuiltinCall) -> IROperand:
    """
    abs(x) for int256 only.

    Returns absolute value, with overflow check for MIN_INT256.
    abs(-2^255) would overflow since 2^255 > MAX_INT256.
    """
    ctx = call.ctx
    b = ctx.builder

    val = call.word("value")

    # Compute negation: neg_val = 0 - val
    neg_val = b.sub(IRLiteral(0), val)

    # Check for MIN_INT256 overflow: if val < 0 and val == neg_val, it's MIN_INT
    # (Only MIN_INT satisfies x == -x for x != 0)
    is_negative = b.slt(val, IRLiteral(0))
    is_min_int = b.eq(val, neg_val)
    bad = b.and_(is_negative, is_min_int)
    b.assert_(b.iszero(bad))

    # Return neg_val if negative, else val
    return b.select(is_negative, neg_val, val)


# Export handlers
HANDLERS = {
    "len": BuiltinLowerer(lower_len, arg_policies={"b": length_source(DataViewKind.CALLDATA)}),
    "empty": BuiltinLowerer(lower_empty),
    "min": BuiltinLowerer(lower_min),
    "max": BuiltinLowerer(lower_max),
    "abs": BuiltinLowerer(lower_abs),
}
