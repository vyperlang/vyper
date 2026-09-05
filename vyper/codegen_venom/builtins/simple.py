"""
Simple built-in functions: len, empty, min, max, abs
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Union

from vyper import ast as vy_ast
from vyper.codegen_venom.builtins._call import BuiltinCall
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import StructureException, TypeMismatch
from vyper.semantics.types import (
    _BytestringT,
    is_unbounded_sequence_type,
    type_contains_unsupported_unbounded_sequence,
)
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import DArrayT
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_len(call: BuiltinCall) -> IROperand:
    """
    len(x) for dynamic arrays, bytes, strings.

    Returns the length stored at the pointer (first word).
    Special case: len(msg.data) returns calldatasize.
    """
    assert call.length is not None
    return call.length


def lower_empty(call: BuiltinCall) -> Union[IROperand, VyperValue]:
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
    node = call.node
    ctx = call.ctx
    typ = get_empty_type(node)

    if typ._is_prim_word:
        return IRLiteral(0)
    if ctx.is_dynamic_tuple_frame_type(typ):
        frame_buf = ctx.allocate_buffer(ctx.dynamic_tuple_frame_size(typ), annotation="empty")
        frame = frame_buf._ptr
        for i, member_t in enumerate(typ.member_types):
            cell = ctx.builder.add(frame, IRLiteral(i * 32))
            if member_t._is_prim_word:
                ctx.builder.mstore(cell, IRLiteral(0))
            else:
                member_vv = _empty_memory_value(ctx, member_t)
                ctx.builder.mstore(cell, member_vv.operand)
        return ctx.dynamic_tuple_frame_value(frame, typ, annotation="empty")
    if type_contains_unsupported_unbounded_sequence(typ):
        raise StructureException(
            "empty() does not support unbounded sequence types inside aggregate types", node
        )
    return _empty_memory_value(ctx, typ)


def get_empty_type(node: vy_ast.Call):
    typ = node.args[0]._metadata["type"].typedef
    expected_typ = node._metadata["type"]

    # Assignment normally permits widening a bytestring. The empty intrinsic
    # deliberately requires an exact nonzero bound, matching legacy codegen.
    if (
        isinstance(typ, _BytestringT)
        and isinstance(expected_typ, _BytestringT)
        and typ.maxlen != 0
        and typ.maxlen != expected_typ.maxlen
    ):
        raise TypeMismatch(f"Cannot cast from empty({typ}) to {expected_typ}", node)

    return typ


def _empty_memory_value(ctx: VenomCodegenContext, typ) -> VyperValue:
    if is_unbounded_sequence_type(typ):
        # Empty INF values have a known exact size: just the zero length word.
        buf = ctx.allocate_buffer(32, annotation="empty")
        ptr = buf._ptr
        ctx.builder.mstore(ptr, IRLiteral(0))
        return ctx.dynamic_memory_value(ptr, typ, annotation="empty")

    # Allocate memory buffer
    val = ctx.new_temporary_value(typ)
    assert isinstance(val.operand, IRVariable)

    # Explicitly zero the memory buffer. For bytestrings/dynarrays, just zero
    # the length word since length=0 means no valid data.
    if isinstance(typ, (_BytestringT, DArrayT)):
        ctx.builder.mstore(val.operand, IRLiteral(0))
    else:
        _zero_memory(ctx, val.operand, typ.memory_bytes_required)

    return val


def _zero_memory(ctx: VenomCodegenContext, ptr: IRVariable, size: int) -> None:
    """Zero out a memory region by writing zeros word by word."""
    for offset in range(0, size, 32):
        dst = ctx.builder.add(ptr, IRLiteral(offset))
        ctx.builder.mstore(dst, IRLiteral(0))


def lower_min(call: BuiltinCall) -> IROperand:
    """min(a, b) - returns smaller of two values."""
    return _lower_minmax(call, is_max=False)


def lower_max(call: BuiltinCall) -> IROperand:
    """max(a, b) - returns larger of two values."""
    return _lower_minmax(call, is_max=True)


def _lower_minmax(call: BuiltinCall, is_max: bool) -> IROperand:
    """
    Common implementation for min/max.

    Uses select: if (a op b) then a else b
    """
    node = call.node
    ctx = call.ctx

    b = ctx.builder

    a_val = call.operand(node.args[0])
    b_val = call.operand(node.args[1])
    typ = node.args[0]._metadata["type"]

    # Choose comparison - signed for most types, unsigned only for uint256
    if typ == UINT256_T:
        cmp_result = b.gt(a_val, b_val) if is_max else b.lt(a_val, b_val)
    else:
        cmp_result = b.sgt(a_val, b_val) if is_max else b.slt(a_val, b_val)

    return b.select(cmp_result, a_val, b_val)


def lower_abs(call: BuiltinCall) -> IROperand:
    """
    abs(x) for int256 only.

    Returns absolute value, with overflow check for MIN_INT256.
    abs(-2^255) would overflow since 2^255 > MAX_INT256.
    """
    node = call.node
    ctx = call.ctx

    b = ctx.builder

    val = call.operand(node.args[0])

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
    "len": lower_len,
    "empty": lower_empty,
    "min": lower_min,
    "max": lower_max,
    "abs": lower_abs,
}
