"""
Byte manipulation built-in functions.

- concat(a, b, ...) - concatenate bytes/strings
- slice(b, start, length) - extract substring
- extract32(b, start) - extract bytes32 from bytearray
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.types import AddressT, BytesM_T, BytesT, IntegerT, StringT
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_concat(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    concat(a, b, ...) -> bytes | string

    Concatenate 2+ bytes/string arguments.
    BytesM args contribute fixed M bytes, bytestring args contribute
    their dynamic length.
    """
    from vyper.codegen_venom.expr import Expr

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

    for arg_node in args:
        arg_t = arg_node._metadata["type"]

        if isinstance(arg_t, _BytestringT):
            # Variable-length bytes/string: copy data, advance by actual length
            # lower_value() handles storage -> memory copy if needed
            arg_ptr = Expr(arg_node, ctx).lower_value()
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
            arg_val = Expr(arg_node, ctx).lower_value()
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


def lower_slice(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    slice(b, start, length) -> bytes | string

    Extract substring from byte array or string.
    Handles special cases: msg.data, self.code, <address>.code.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    src_node = node.args[0]
    start_node = node.args[1]
    length_node = node.args[2]

    src_t = src_node._metadata["type"]
    out_t = node._metadata["type"]

    # Check for adhoc slice macros (msg.data, self.code, <addr>.code)
    if _is_adhoc_slice(src_node):
        return _lower_adhoc_slice(node, ctx)

    # Evaluate arguments in left-to-right order for correct order of evaluation
    # (src must be evaluated before start/length, since their side effects may modify src)
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # lower_value() handles storage -> memory copy if needed
        src_ptr = Expr(src_node, ctx).lower_value()
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    elif isinstance(src_t, BytesM_T):
        # bytesM: fixed length, value is the data (left-aligned)
        src_val = Expr(src_node, ctx).lower_value()
        src_len = IRLiteral(src_t.m)
        # Need to store to memory first to slice from it
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr
    else:
        # bytes32 or other 32-byte type
        src_val = Expr(src_node, ctx).lower_value()
        src_len = IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    # Evaluate start and length AFTER src to maintain left-to-right evaluation order
    start = Expr(start_node, ctx).lower_value()
    length = Expr(length_node, ctx).lower_value()

    # Bounds check: start + length <= src_length, with overflow check
    end = b.add(start, length)
    # Check for arithmetic overflow (if end wrapped around, end < start)
    arithmetic_overflow = b.lt(end, start)
    buffer_oob = b.gt(end, src_len)
    oob = b.or_(arithmetic_overflow, buffer_oob)
    b.assert_(b.iszero(oob))

    # Allocate output buffer
    out_val = ctx.new_temporary_value(out_t)
    out_data = ctx.add_offset(out_val.ptr(), IRLiteral(32))

    # Copy bytes from src_data + start to out_data
    copy_src = b.add(src_data, start)
    ctx.copy_memory_dynamic(out_data.operand, copy_src, length)

    # Store length
    ctx.ptr_store(out_val.ptr(), length)
    return out_val


def _is_adhoc_slice(node: vy_ast.VyperNode) -> bool:
    """Check if node represents msg.data, self.code, or <addr>.code."""
    if not isinstance(node, vy_ast.Attribute):
        return False

    # msg.data
    if isinstance(node.value, vy_ast.Name):
        if node.value.id == "msg" and node.attr == "data":
            return True
        if node.value.id == "self" and node.attr == "code":
            return True

    # <addr>.code
    if node.attr == "code":
        return True

    return False


def _lower_adhoc_slice(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    Lower slice() for special sources: msg.data, self.code, <addr>.code.

    These use specialized opcodes: calldatacopy, codecopy, extcodecopy.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    src_node = node.args[0]
    start_node = node.args[1]
    length_node = node.args[2]

    start = Expr(start_node, ctx).lower_value()
    length = Expr(length_node, ctx).lower_value()

    out_t = node._metadata["type"]
    out_val = ctx.new_temporary_value(out_t)
    out_data = ctx.add_offset(out_val.ptr(), IRLiteral(32))

    # Determine which opcode to use
    if isinstance(src_node.value, vy_ast.Name):
        if src_node.value.id == "msg" and src_node.attr == "data":
            # msg.data: use calldatacopy, bounds check against calldatasize
            src_len = b.calldatasize()
            end = b.add(start, length)
            # Check for arithmetic overflow (if end wrapped around, end < start)
            arithmetic_overflow = b.lt(end, start)
            buffer_oob = b.gt(end, src_len)
            oob = b.or_(arithmetic_overflow, buffer_oob)
            b.assert_(b.iszero(oob))
            # calldatacopy(destOffset, offset, size)
            b.calldatacopy(out_data.operand, start, length)
            ctx.ptr_store(out_val.ptr(), length)
            return out_val

        elif src_node.value.id == "self" and src_node.attr == "code":
            # self.code: use codecopy, bounds check against codesize
            src_len = b.codesize()
            end = b.add(start, length)
            # Check for arithmetic overflow (if end wrapped around, end < start)
            arithmetic_overflow = b.lt(end, start)
            buffer_oob = b.gt(end, src_len)
            oob = b.or_(arithmetic_overflow, buffer_oob)
            b.assert_(b.iszero(oob))
            # codecopy(destOffset, offset, size)
            b.codecopy(out_data.operand, start, length)
            ctx.ptr_store(out_val.ptr(), length)
            return out_val

    # <addr>.code: use extcodecopy
    addr = Expr(src_node.value, ctx).lower_value()
    src_len = b.extcodesize(addr)
    end = b.add(start, length)
    # Check for arithmetic overflow (if end wrapped around, end < start)
    arithmetic_overflow = b.lt(end, start)
    buffer_oob = b.gt(end, src_len)
    oob = b.or_(arithmetic_overflow, buffer_oob)
    b.assert_(b.iszero(oob))
    # extcodecopy(address, destOffset, offset, size)
    b.extcodecopy(addr, out_data.operand, start, length)
    ctx.ptr_store(out_val.ptr(), length)
    return out_val


def lower_extract32(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    extract32(b, start, output_type=bytes32) -> bytes32 | int | address

    Extract 32 bytes from bytearray at given position.
    Result type can be specified via output_type kwarg.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    src_node = node.args[0]
    start_node = node.args[1]
    src_t = src_node._metadata["type"]

    # Evaluate arguments in left-to-right order for correct order of evaluation
    # (src must be evaluated before start, since start's side effects may modify src)
    src_len: IROperand
    src_data: IROperand
    if isinstance(src_t, _BytestringT):
        # lower_value() handles storage -> memory copy if needed
        src_ptr = Expr(src_node, ctx).lower_value()
        src_len = b.mload(src_ptr)
        src_data = b.add(src_ptr, IRLiteral(32))
    else:
        # bytes32 or other fixed type - shouldn't happen but handle it
        src_val = Expr(src_node, ctx).lower_value()
        src_len = IRLiteral(32)
        tmp_buf = ctx.allocate_buffer(32)
        b.mstore(tmp_buf._ptr, src_val)
        src_data = tmp_buf._ptr

    # Evaluate start AFTER src to maintain left-to-right evaluation order
    start = Expr(start_node, ctx).lower_value()

    # Bounds check: start + 32 <= length
    end = b.add(start, IRLiteral(32))
    oob = b.gt(end, src_len)
    b.assert_(b.iszero(oob))

    # Load 32 bytes at offset
    load_ptr = b.add(src_data, start)
    result = b.mload(load_ptr)

    # Apply type-specific clamping if needed
    out_t = node._metadata["type"]
    return _clamp_extract32_result(result, out_t, ctx)


def _clamp_extract32_result(val: IROperand, out_t, ctx: VenomCodegenContext) -> IROperand:
    """Apply bounds check for extract32 output type."""
    b = ctx.builder

    if isinstance(out_t, IntegerT):
        # Need to clamp to type bounds for signed/unsigned integers
        if out_t.bits < 256:
            if out_t.is_signed:
                # For signed types, check signextend(val) == val
                # This ensures the value's high bits match the sign bit
                bytes_minus_1 = out_t.bits // 8 - 1
                canonical = b.signextend(IRLiteral(bytes_minus_1), val)
                b.assert_(b.eq(val, canonical))
            else:
                # For unsigned types, check value fits in type range
                mask = (1 << out_t.bits) - 1
                too_big = b.gt(val, IRLiteral(mask))
                b.assert_(b.iszero(too_big))
    elif isinstance(out_t, AddressT):
        # Address is 160 bits, ensure high 96 bits are zero
        mask = (1 << 160) - 1
        too_big = b.gt(val, IRLiteral(mask))
        b.assert_(b.iszero(too_big))

    # bytes32 and bytesM need no clamping
    return val


# Export handlers
HANDLERS = {"concat": lower_concat, "slice": lower_slice, "extract32": lower_extract32}
