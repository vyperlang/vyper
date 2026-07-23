"""
Byte manipulation built-in functions.

- concat(a, b, ...) - concatenate bytes/strings
- slice(b, start, length) - extract substring
- extract32(b, start) - extract bytes32 from bytearray
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from vyper.codegen_venom.arithmetic import AnyPrimType, clamp_basetype
from vyper.codegen_venom.builtins._call import BuiltinLowerer, PreparedBuiltinCall
from vyper.codegen_venom.call_args import DataView, DataViewKind, data_source
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.types import BytesM_T, BytesT
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _assert_slice_bounds(
    ctx: VenomCodegenContext, start: IROperand, length: IROperand, src_len: IROperand
) -> None:
    """Assert `start + length <= src_len` with overflow protection."""
    b = ctx.builder
    end = b.add(start, length)
    arithmetic_overflow = b.lt(end, start)
    buffer_oob = b.gt(end, src_len)
    oob = b.or_(arithmetic_overflow, buffer_oob)
    b.assert_(b.iszero(oob))


def lower_concat(call: PreparedBuiltinCall) -> VyperValue:
    """
    concat(a, b, ...) -> bytes | string

    Concatenate 2+ bytes/string arguments.
    BytesM args contribute fixed M bytes, bytestring args contribute
    their dynamic length.
    """
    ctx = call.ctx
    b = ctx.builder

    out_typ = call.return_type
    assert isinstance(out_typ, _BytestringT)

    # Allocate output buffer (length word + data)
    out_val = ctx.new_temporary_value(out_typ)
    data_ptr = ctx.add_offset(out_val.ptr(), IRLiteral(32))

    # Track current offset as a variable
    offset_local = ctx.new_temporary_value(BytesT(32))  # just need 32 bytes
    ctx.ptr_store(offset_local.ptr(), IRLiteral(0))

    for i in range(call.arg_count):
        arg_t = call.arg_type(i)

        if isinstance(arg_t, _BytestringT):
            # Variable-length bytes/string: copy data, advance by actual length.
            # The argument is already prepared as stable memory.
            arg_ptr = call.memory(i)
            arg_len = b.mload(arg_ptr)
            arg_data = b.add(arg_ptr, IRLiteral(32))
            offset = ctx.ptr_load(offset_local.ptr())
            dst = b.add(data_ptr.operand, offset)
            ctx.copy_memory_dynamic(dst, arg_data, arg_len)
            new_offset = b.add(offset, arg_len)
            ctx.ptr_store(offset_local.ptr(), new_offset)
        else:
            # Fixed bytesM: the value is already left-aligned in 32 bytes
            # Store full 32 bytes and advance by M
            arg_val = call.word(i)
            m = arg_t.m
            offset = ctx.ptr_load(offset_local.ptr())
            dst = b.add(data_ptr.operand, offset)
            b.mstore(dst, arg_val)
            new_offset = b.add(offset, IRLiteral(m))
            ctx.ptr_store(offset_local.ptr(), new_offset)

    # Store final length at output buffer
    final_len = ctx.ptr_load(offset_local.ptr())
    ctx.ptr_store(out_val.ptr(), final_len)
    return out_val


def lower_slice(call: PreparedBuiltinCall) -> VyperValue:
    """
    slice(b, start, length) -> bytes | string

    Extract substring from byte array or string.
    Handles special cases: msg.data, self.code, <address>.code.
    """
    ctx = call.ctx
    b = ctx.builder

    src = call.data_source("b")
    out_t = call.return_type

    if isinstance(src, DataView):
        return _lower_data_view_slice(call, src)

    src_t = src.typ

    # Arguments were lowered in source order (src before start/length,
    # frozen against their side effects where necessary).
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # Variable-length values are prepared as stable memory.
        src_ptr = call.memory("b")
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    else:
        # bytesM (incl. bytes32): fixed length, the value is the data
        # (left-aligned). Store to memory first to slice from it.
        src_val = call.word("b")
        src_len = IRLiteral(src_t.m) if isinstance(src_t, BytesM_T) else IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    start = call.word("start")
    length = call.word("length")

    _assert_slice_bounds(ctx, start, length, src_len)

    # Allocate output buffer
    out_val = ctx.new_temporary_value(out_t)
    out_data = ctx.add_offset(out_val.ptr(), IRLiteral(32))

    # Copy bytes from src_data + start to out_data
    copy_src = b.add(src_data, start)
    assert isinstance(out_data.operand, IRVariable)
    ctx.copy_memory_dynamic(out_data.operand, copy_src, length)

    # Store length
    ctx.ptr_store(out_val.ptr(), length)
    return out_val


def _lower_data_view_slice(call: PreparedBuiltinCall, src: DataView) -> VyperValue:
    """
    Lower slice() for special sources: msg.data, self.code, <addr>.code.

    These use specialized opcodes: calldatacopy, codecopy, extcodecopy.
    """
    ctx = call.ctx
    b = ctx.builder

    start = call.word("start")
    length = call.word("length")

    out_t = call.return_type
    out_val = ctx.new_temporary_value(out_t)
    out_data = ctx.add_offset(out_val.ptr(), IRLiteral(32))
    assert isinstance(out_data.operand, IRVariable)

    if src.kind is DataViewKind.CALLDATA:
        src_len = b.calldatasize()
        _assert_slice_bounds(ctx, start, length, src_len)
        b.calldatacopy(out_data.operand, start, length)
    elif src.kind is DataViewKind.SELF_CODE:
        src_len = b.codesize()
        _assert_slice_bounds(ctx, start, length, src_len)
        b.codecopy(out_data.operand, start, length)
    else:
        addr = src.address_operand()
        src_len = b.extcodesize(addr)
        _assert_slice_bounds(ctx, start, length, src_len)
        b.extcodecopy(addr, out_data.operand, start, length)

    ctx.ptr_store(out_val.ptr(), length)
    return out_val


def lower_extract32(call: PreparedBuiltinCall) -> IROperand:
    """
    extract32(b, start, output_type=bytes32) -> bytes32 | int | address

    Extract 32 bytes from bytearray at given position.
    Result type can be specified via output_type kwarg.
    """
    ctx = call.ctx
    b = ctx.builder

    src_t = call.arg_type("b")

    # Arguments have already been evaluated in left-to-right order.
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # Variable-length values are prepared as stable memory.
        src_ptr = call.memory("b")
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    else:
        # bytes32 or other fixed type - shouldn't happen but handle it
        src_val = call.word("b")
        src_len = IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    start = call.word("start")

    # Bounds check: start + 32 <= length
    _assert_slice_bounds(ctx, start, IRLiteral(32), src_len)

    # Load 32 bytes at offset
    load_ptr = b.add(src_data, start)
    result = b.mload(load_ptr)

    # Apply type-specific clamping if needed
    out_t = call.type_kwarg("output_type")
    assert out_t == call.return_type
    return clamp_basetype(b, result, cast(AnyPrimType, out_t))


# Export handlers
HANDLERS = {
    "concat": BuiltinLowerer(lower_concat),
    "slice": BuiltinLowerer(
        lower_slice,
        arg_policies={
            "b": data_source(
                DataViewKind.CALLDATA, DataViewKind.SELF_CODE, DataViewKind.EXTERNAL_CODE
            )
        },
    ),
    "extract32": BuiltinLowerer(lower_extract32),
}
