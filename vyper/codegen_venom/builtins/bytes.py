"""
Byte manipulation built-in functions.

- concat(a, b, ...) - concatenate bytes/strings
- slice(b, start, length) - extract substring
- extract32(b, start) - extract bytes32 from bytearray
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.codegen_venom.arithmetic import clamp_basetype
from vyper.codegen_venom.builtins._call import BuiltinCall, callsite, is_data_view
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.types import BytesM_T, BytesT, StringT
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


def lower_concat(call: BuiltinCall) -> VyperValue:
    """
    concat(a, b, ...) -> bytes | string

    Concatenate 2+ bytes/string arguments.
    BytesM args contribute fixed M bytes, bytestring args contribute
    their dynamic length.
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder
    args = node.args

    # Calculate max output length (for buffer allocation)
    max_len = 0
    for arg in args:
        arg_t = arg._metadata["type"]
        if isinstance(arg_t, _BytestringT):
            max_len += arg_t.maxlen
        else:  # BytesM_T
            max_len += arg_t.m

    # Determine output type (string or bytes)
    first_t = args[0]._metadata["type"]
    out_typ: _BytestringT
    if isinstance(first_t, StringT):
        out_typ = StringT(max_len)
    else:
        out_typ = BytesT(max_len)

    # Allocate output buffer (length word + data)
    out_val = ctx.new_temporary_value(out_typ)
    data_ptr = ctx.add_offset(out_val.ptr(), IRLiteral(32))

    # Track current offset as a variable
    offset_local = ctx.new_temporary_value(BytesT(32))  # just need 32 bytes
    ctx.ptr_store(offset_local.ptr(), IRLiteral(0))

    for i, arg_node in enumerate(args):
        arg_t = arg_node._metadata["type"]

        if isinstance(arg_t, _BytestringT):
            # Variable-length bytes/string: copy data, advance by actual length
            # unwrap handles storage -> memory copy if needed
            arg_ptr = call.arg_operand(i)
            assert isinstance(arg_ptr, IRVariable)
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
            arg_val = call.arg_operand(i)
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


def lower_slice(call: BuiltinCall) -> VyperValue:
    """
    slice(b, start, length) -> bytes | string

    Extract substring from byte array or string.
    Handles special cases: msg.data, self.code, <address>.code.
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    src_node = node.args[0]
    src_t = src_node._metadata["type"]
    out_t = node._metadata["type"]

    # Adhoc slice macros (msg.data, self.code, <addr>.code)
    if is_data_view(src_node):
        return _lower_data_view_slice(call)

    # Arguments were lowered in source order (src before start/length,
    # frozen against their side effects where necessary).
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # unwrap handles storage -> memory copy if needed
        src_ptr = call.arg_operand(0)
        assert isinstance(src_ptr, IRVariable)
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    else:
        # bytesM (incl. bytes32): fixed length, the value is the data
        # (left-aligned). Store to memory first to slice from it.
        src_val = call.arg_operand(0)
        src_len = IRLiteral(src_t.m) if isinstance(src_t, BytesM_T) else IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    start = call.arg_operand(1)
    length = call.arg_operand(2)

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


def _lower_data_view_slice(call: BuiltinCall) -> VyperValue:
    """
    Lower slice() for special sources: msg.data, self.code, <addr>.code.

    These use specialized opcodes: calldatacopy, codecopy, extcodecopy.
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    src_node = node.args[0]
    assert isinstance(src_node, vy_ast.Attribute)

    start = call.arg_operand(1)
    length = call.arg_operand(2)

    out_t = node._metadata["type"]
    out_val = ctx.new_temporary_value(out_t)
    out_data = ctx.add_offset(out_val.ptr(), IRLiteral(32))
    assert isinstance(out_data.operand, IRVariable)

    # Determine which opcode to use
    if isinstance(src_node.value, vy_ast.Name):
        if src_node.value.id == "msg" and src_node.attr == "data":
            # msg.data: use calldatacopy, bounds check against calldatasize
            src_len = b.calldatasize()
            _assert_slice_bounds(ctx, start, length, src_len)
            # calldatacopy(destOffset, offset, size)
            b.calldatacopy(out_data.operand, start, length)
            ctx.ptr_store(out_val.ptr(), length)
            return out_val

        elif src_node.value.id == "self" and src_node.attr == "code":
            # self.code: use codecopy, bounds check against codesize
            src_len = b.codesize()
            _assert_slice_bounds(ctx, start, length, src_len)
            # codecopy(destOffset, offset, size)
            b.codecopy(out_data.operand, start, length)
            ctx.ptr_store(out_val.ptr(), length)
            return out_val

    # <addr>.code: use extcodecopy. The address subexpression was lowered
    # in the view's place, before start/length.
    addr = call.arg_operand(0)
    src_len = b.extcodesize(addr)
    _assert_slice_bounds(ctx, start, length, src_len)
    # extcodecopy(address, destOffset, offset, size)
    b.extcodecopy(addr, out_data.operand, start, length)
    ctx.ptr_store(out_val.ptr(), length)
    return out_val


@callsite(type_kwargs=("output_type",))
def lower_extract32(call: BuiltinCall) -> IROperand:
    """
    extract32(b, start, output_type=bytes32) -> bytes32 | int | address

    Extract 32 bytes from bytearray at given position.
    Result type can be specified via output_type kwarg.
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    src_t = node.args[0]._metadata["type"]

    # Arguments have already been evaluated in left-to-right order.
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # unwrap handles storage -> memory copy if needed
        src_ptr = call.arg_operand(0)
        assert isinstance(src_ptr, IRVariable)
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    else:
        # bytes32 or other fixed type - shouldn't happen but handle it
        src_val = call.arg_operand(0)
        src_len = IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    start = call.arg_operand(1)

    # Bounds check: start + 32 <= length
    _assert_slice_bounds(ctx, start, IRLiteral(32), src_len)

    # Load 32 bytes at offset
    load_ptr = b.add(src_data, start)
    result = b.mload(load_ptr)

    # Apply type-specific clamping if needed
    out_t = node._metadata["type"]
    return clamp_basetype(b, result, out_t)


# Export handlers
HANDLERS = {"concat": lower_concat, "slice": lower_slice, "extract32": lower_extract32}
