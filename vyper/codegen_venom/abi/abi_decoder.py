"""
ABI decoding for Venom IR.

Port of ABI decoding logic from vyper/codegen/core.py for direct AST-to-Venom codegen.

ABI decoding reads data in ABI format and writes to Vyper memory layout.
Unlike the legacy code where decoding was embedded in make_setter, this module
provides a clean abi_decode_to_buf() that does one thing: decode ABI-encoded
data to Vyper memory layout. The optimizer eliminates redundant copies.

Security: When decoding untrusted data from memory, we need bounds checks
to prevent buffer overruns. The `hi` parameter provides the upper bound
of valid buffer data and must be passed through all recursive calls.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper.codegen.core import is_tuple_like
from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    DArrayT,
    DecimalT,
    FlagT,
    IntegerT,
    InterfaceT,
    SArrayT,
    VyperType,
    _BytestringT,
)
from vyper.semantics.types.shortcuts import BYTES32_T, INT256_T, UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def needs_clamp(typ: VyperType) -> bool:
    """
    Check if ABI-decoded value needs validation.

    Port of needs_clamp() from vyper/codegen/core.py.
    Returns True if the type requires clamping/validation after ABI decode.
    """
    if isinstance(typ, (_BytestringT, DArrayT)):
        return True
    if isinstance(typ, FlagT):
        return len(typ._flag_members) < 256
    if isinstance(typ, SArrayT):
        return needs_clamp(typ.value_type)
    if is_tuple_like(typ):
        return any(needs_clamp(m) for m in typ.tuple_members())  # type: ignore[attr-defined]
    if typ._is_prim_word:
        return typ not in (INT256_T, UINT256_T, BYTES32_T)

    raise CompilerPanic(f"needs_clamp: unhandled type {typ}")


def int_clamp(ctx: VenomCodegenContext, val: IROperand, bits: int, signed: bool) -> IROperand:
    """
    Validate integer is in range.

    Port of int_clamp() from vyper/codegen/core.py.

    For signed integers, we check that signextend(val) == val.
    For unsigned integers, we check that the high bits are zero.
    """
    if bits >= 256:
        raise CompilerPanic(f"invalid clamp: {bits} >= 256")

    b = ctx.builder

    if signed:
        # signextend and compare to original
        # For signed ints, the canonical representation has all bits above
        # the sign bit equal to the sign bit.
        bytes_minus_1 = bits // 8 - 1
        canonical = b.signextend(IRLiteral(bytes_minus_1), val)
        b.assert_(b.eq(val, canonical))
    else:
        # check high bits are zero: assert iszero(val >> bits)
        b.assert_(b.iszero(b.shr(IRLiteral(bits), val)))

    return val


def bytes_clamp(ctx: VenomCodegenContext, val: IROperand, m: int) -> IROperand:
    """
    Validate bytesM has zero padding in low bits.

    Port of bytes_clamp() from vyper/codegen/core.py.

    BytesM is left-aligned, so the low (32-m)*8 bits must be zero.
    We check: assert iszero(val << (m * 8))
    """
    if not (0 < m <= 32):
        raise CompilerPanic(f"bad type: bytes{m}")

    b = ctx.builder
    # Left-aligned: low (32-m)*8 bits must be zero
    # val << (m*8) should be zero
    b.assert_(b.iszero(b.shl(IRLiteral(m * 8), val)))
    return val


def clamp_basetype(ctx: VenomCodegenContext, val: IROperand, typ: VyperType) -> IROperand:
    """
    Validate primitive value, return clamped value.

    Port of clamp_basetype() from vyper/codegen/core.py.
    Dispatches to the appropriate clamping function based on type.
    """
    if not typ._is_prim_word:
        raise CompilerPanic(f"{typ} passed to clamp_basetype")

    if isinstance(typ, FlagT):
        bits = len(typ._flag_members)
        return int_clamp(ctx, val, bits, signed=False)

    elif isinstance(typ, (IntegerT, DecimalT)):
        if typ.bits == 256:
            return val
        return int_clamp(ctx, val, typ.bits, signed=typ.is_signed)

    elif isinstance(typ, BytesM_T):
        if typ.m == 32:
            return val
        return bytes_clamp(ctx, val, typ.m)

    elif isinstance(typ, (AddressT, InterfaceT)):
        return int_clamp(ctx, val, 160, signed=False)

    elif typ == BoolT():
        return int_clamp(ctx, val, 1, signed=False)

    raise CompilerPanic(f"Unknown type for clamping: {typ}")


def clamp_bytestring(
    ctx: VenomCodegenContext, src: VyperValue, typ: _BytestringT, hi: IROperand = None
) -> None:
    """
    Validate bytestring length and bounds.

    Port of clamp_bytestring() from vyper/codegen/core.py.

    Checks:
    1. length <= maxlen
    2. If hi is provided: item_end <= hi (prevents buffer overrun)
    """
    b = ctx.builder
    assert src.location is not None, "src must have a location for bytestring clamping"
    length = b.load(src.operand, src.location)  # Length word at start

    # Check length <= maxlen
    b.assert_(b.iszero(b.gt(length, IRLiteral(typ.maxlen))))

    if hi is not None:
        # Check item_end <= hi
        # item_end = src + 32 + length
        item_end = b.add(src.operand, IRLiteral(32))
        item_end = b.add(item_end, length)
        b.assert_(b.iszero(b.gt(item_end, hi)))


def clamp_dyn_array(
    ctx: VenomCodegenContext, src: VyperValue, typ: DArrayT, hi: IROperand = None
) -> None:
    """
    Validate DynArray count and bounds.

    Port of clamp_dyn_array() from vyper/codegen/core.py.

    Checks:
    1. count <= max_count
    2. If hi is provided: payload_end <= hi (prevents buffer overrun)
    """
    b = ctx.builder
    assert src.location is not None, "src must have a location for dyn_array clamping"
    count = b.load(src.operand, src.location)  # Count word at start

    # Check count <= max_count
    b.assert_(b.iszero(b.gt(count, IRLiteral(typ.count))))

    if hi is not None:
        # Check payload_end <= hi
        # payload_end = src + 32 + count * elem_static_size
        elem_static_size = typ.value_type.abi_type.embedded_static_size()
        payload_size = b.mul(count, IRLiteral(elem_static_size))
        payload_size = b.add(payload_size, IRLiteral(32))
        item_end = b.add(src.operand, payload_size)
        b.assert_(b.iszero(b.gt(item_end, hi)))


def _getelemptr_abi(
    ctx: VenomCodegenContext, parent: VyperValue, member_typ: VyperType, static_offset: int
) -> VyperValue:
    """
    Navigate to ABI-encoded element.

    Port of _getelemptr_abi_helper() from vyper/codegen/core.py.

    For static types: returns parent + static_offset
    For dynamic types: reads offset at static location, adds to parent base
                      (double dereference pattern)

    Returns VyperValue with same location as parent, typed as member_typ.
    """
    b = ctx.builder
    loc = parent.location
    assert loc is not None, "parent must have a location for ABI element access"

    # Calculate static location
    if static_offset == 0:
        static_loc = parent.operand
    else:
        static_loc = b.add(parent.operand, IRLiteral(static_offset))

    if member_typ.abi_type.is_dynamic():
        # Double dereference: read offset, add to parent base
        offset_val = b.load(static_loc, loc)
        actual_ptr = b.add(parent.operand, offset_val)
        # Security: prevent underflow attacks
        # assert actual_ptr >= parent
        b.assert_(b.iszero(b.lt(actual_ptr, parent.operand)))
        return _make_ptr_value(actual_ptr, loc, member_typ)
    else:
        # Static: data is inline
        return _make_ptr_value(static_loc, loc, member_typ)


def _make_ptr_value(operand, location: DataLocation, typ) -> VyperValue:
    """Create a VyperValue with Ptr for a computed pointer."""
    if location == DataLocation.MEMORY:
        buf = Buffer(_ptr=operand, size=typ.memory_bytes_required, annotation="abi_decoder")
        ptr = Ptr(operand=operand, location=location, buf=buf)
    else:
        ptr = Ptr(operand=operand, location=location)
    return VyperValue.from_ptr(ptr, typ)


def _decode_primitive(
    ctx: VenomCodegenContext, dst: IROperand, src: VyperValue, typ: VyperType
) -> None:
    """Decode a primitive (word-sized) type."""
    b = ctx.builder
    assert src.location is not None, "src must have a location for primitive decoding"
    val: IROperand = b.load(src.operand, src.location)

    if needs_clamp(typ):
        val = clamp_basetype(ctx, val, typ)

    b.mstore(dst, val)


def _decode_bytestring(
    ctx: VenomCodegenContext,
    dst: IROperand,
    src: VyperValue,
    typ: _BytestringT,
    hi: IROperand = None,
) -> None:
    """
    Decode a bytestring (Bytes/String) type.

    ABI and Vyper layouts are the same: [length word][data...]
    So we just validate and copy.
    """
    # Validate length and bounds
    clamp_bytestring(ctx, src, typ, hi)

    # Copy: length word + data (up to maxlen + 32 bytes)
    size = typ.memory_bytes_required
    assert src.location is not None, "src must have a location for bytestring decoding"
    ctx.builder.copy_to_memory(dst, src.operand, IRLiteral(size), src.location)


def _decode_dyn_array(
    ctx: VenomCodegenContext, dst: IROperand, src: VyperValue, typ: DArrayT, hi: IROperand = None
) -> None:
    """
    Decode a dynamic array.

    Layout: [count word][elements...]
    Elements are decoded recursively.
    """
    b = ctx.builder
    loc = src.location
    assert loc is not None, "src must have a location for dynamic array decoding"
    elem_typ = typ.value_type
    elem_abi_t = elem_typ.abi_type

    # Validate count and bounds
    clamp_dyn_array(ctx, src, typ, hi)

    # Copy count word
    count = b.load(src.operand, loc)
    b.mstore(dst, count)

    # If element type doesn't need decoding, just copy
    if not needs_clamp(elem_typ) and not elem_abi_t.is_dynamic():
        # Straight copy of elements
        elem_mem_size = elem_typ.memory_bytes_required
        # Size = count * elem_mem_size
        size = b.mul(count, IRLiteral(elem_mem_size))
        src_data = b.add(src.operand, IRLiteral(32))
        dst_data = b.add(dst, IRLiteral(32))
        b.copy_to_memory(dst_data, src_data, size, loc)
        return

    # Need element-by-element decode
    elem_static_size = elem_abi_t.embedded_static_size()
    elem_mem_size = elem_typ.memory_bytes_required

    # Create loop blocks
    loop_header = b.create_block("darr_dec_hdr")
    b.append_block(loop_header)
    loop_body = b.create_block("darr_dec_body")
    b.append_block(loop_body)
    loop_exit = b.create_block("darr_dec_exit")
    b.append_block(loop_exit)

    # Initialize loop counter (always in memory)
    i_val = ctx.new_temporary_value(UINT256_T)
    ctx.ptr_store(i_val.ptr(), IRLiteral(0))

    # Jump to header
    b.jmp(loop_header.label)

    # --- Loop header: check i < count ---
    b.set_block(loop_header)
    i = ctx.ptr_load(i_val.ptr())  # Loop counter is in memory
    # Reload count from source
    count_hdr = b.load(src.operand, loc)
    done = b.iszero(b.lt(i, count_hdr))
    b.jnz(done, loop_exit.label, loop_body.label)

    # --- Loop body ---
    b.set_block(loop_body)

    # Re-load i (from memory)
    i = ctx.ptr_load(i_val.ptr())

    # Get source element pointer (ABI layout)
    src_data = b.add(src.operand, IRLiteral(32))
    if elem_abi_t.is_dynamic():
        # Navigate through offset
        static_loc = b.add(src_data, b.mul(i, IRLiteral(elem_static_size)))
        offset_val = b.load(static_loc, loc)
        elem_src_ptr = b.add(src_data, offset_val)
        # Security check: prevent underflow
        b.assert_(b.iszero(b.lt(elem_src_ptr, src_data)))
        # Bounds check: ensure element static footprint fits within buffer
        if hi is not None:
            elem_end = b.add(elem_src_ptr, IRLiteral(elem_static_size))
            b.assert_(b.iszero(b.gt(elem_end, hi)))
    else:
        elem_src_ptr = b.add(src_data, b.mul(i, IRLiteral(elem_static_size)))

    # Wrap as VyperValue for recursive call
    elem_src = _make_ptr_value(elem_src_ptr, loc, elem_typ)

    # Get destination element pointer (Vyper layout)
    dst_data = b.add(dst, IRLiteral(32))
    elem_dst = b.add(dst_data, b.mul(i, IRLiteral(elem_mem_size)))

    # Recursively decode element
    _abi_decode_to_buf(ctx, elem_dst, elem_src, hi)

    # Increment counter
    new_i = b.add(i, IRLiteral(1))
    ctx.ptr_store(i_val.ptr(), new_i)
    b.jmp(loop_header.label)

    # --- Exit block ---
    b.set_block(loop_exit)


def _decode_complex(
    ctx: VenomCodegenContext, dst: IROperand, src: VyperValue, typ: VyperType, hi: IROperand = None
) -> None:
    """
    Decode a complex type (tuple/struct/static array).

    Iterates over members and decodes each one.
    """
    b = ctx.builder

    # Bounds check: ensure the static footprint fits within the buffer
    if hi is not None:
        static_size = typ.abi_type.static_size()
        item_end = b.add(src.operand, IRLiteral(static_size))
        b.assert_(b.iszero(b.gt(item_end, hi)))

    if is_tuple_like(typ):
        items = list(typ.tuple_items())  # type: ignore[attr-defined]
    elif isinstance(typ, SArrayT):
        items = [(i, typ.value_type) for i in range(typ.count)]
    else:
        raise CompilerPanic(f"Cannot decode complex type: {typ}")

    # Track ABI and Vyper offsets separately
    abi_offset = 0
    vyper_offset = 0

    for _key, elem_typ in items:
        # Get source pointer (ABI layout) - returns VyperValue
        elem_src = _getelemptr_abi(ctx, src, elem_typ, abi_offset)

        # Get destination pointer (Vyper layout)
        if vyper_offset == 0:
            elem_dst = dst
        else:
            elem_dst = b.add(dst, IRLiteral(vyper_offset))

        # Recursively decode element
        _abi_decode_to_buf(ctx, elem_dst, elem_src, hi)

        # Advance offsets
        abi_offset += elem_typ.abi_type.embedded_static_size()
        vyper_offset += elem_typ.memory_bytes_required


def _abi_decode_to_buf(
    ctx: VenomCodegenContext, dst: IROperand, src: VyperValue, hi: IROperand = None
) -> None:
    """
    Internal decoder dispatcher.

    Decodes ABI-encoded src to Vyper-encoded dst based on src.typ.
    """
    src_typ = src.typ
    assert src_typ is not None, "src must have a type for ABI decoding"
    assert src.location is not None, "src must have a location"

    if src_typ._is_prim_word:
        _decode_primitive(ctx, dst, src, src_typ)
    elif isinstance(src_typ, _BytestringT):
        _decode_bytestring(ctx, dst, src, src_typ, hi)
    elif isinstance(src_typ, DArrayT):
        _decode_dyn_array(ctx, dst, src, src_typ, hi)
    elif is_tuple_like(src_typ) or isinstance(src_typ, SArrayT):
        _decode_complex(ctx, dst, src, src_typ, hi)
    else:
        raise CompilerPanic(f"Cannot ABI decode type: {src_typ}")


def abi_decode_to_buf(
    ctx: VenomCodegenContext, dst: IROperand, src: VyperValue, hi: IROperand = None
) -> None:
    """
    Decode ABI-encoded src to Vyper-encoded dst.

    This is a pure decode operation - reads ABI layout, writes Vyper layout.
    The optimizer eliminates redundant copies if possible.

    Args:
        ctx: Venom codegen context
        dst: Destination buffer (Vyper memory layout)
        src: Source ABI data (VyperValue with location and type)
        hi: Upper bound of valid buffer. Required when decoding untrusted data
            (calldata in memory, returndata, user Bytes). Prevents overread attacks.
    """
    return _abi_decode_to_buf(ctx, dst, src, hi)
