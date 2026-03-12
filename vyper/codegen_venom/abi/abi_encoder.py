"""
ABI encoding/decoding for Venom IR.

Port of vyper/codegen/abi_encoder.py for direct AST-to-Venom codegen.

The ABI encoding follows the Ethereum ABI spec:
- Static types are encoded inline at fixed offsets
- Dynamic types (bytes, string, arrays) store an offset in the static section
  and the actual data in a dynamic tail section
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper.codegen.abi_encoder import abi_encoding_matches_vyper
from vyper.codegen.core import is_tuple_like
from vyper.exceptions import CompilerPanic
from vyper.semantics.types import DArrayT, SArrayT, VyperType, _BytestringT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext
    from vyper.codegen_venom.types import VyperValue


def _is_complex_type(typ: VyperType) -> bool:
    """Check if type is tuple/struct/static array (needs element-by-element encoding)."""
    return is_tuple_like(typ) or isinstance(typ, SArrayT)


def _get_element_ptr(
    ctx: VenomCodegenContext, parent_ptr: IROperand, key: IROperand, parent_typ: VyperType
) -> tuple[IROperand, VyperType]:
    """
    Get pointer to element and its type.

    For tuples/structs, key is an index/name, for arrays key is an index.
    Returns (element_ptr, element_type).
    """
    b = ctx.builder

    if is_tuple_like(parent_typ):
        # key is an integer index into tuple/struct
        # Calculate offset: sum of preceding element sizes
        if isinstance(key, IRLiteral):
            idx = key.value
        else:
            raise CompilerPanic("Dynamic tuple indexing not supported in ABI encode")

        items = parent_typ.tuple_items()  # type: ignore[attr-defined]
        offset = 0
        for i, (_k, t) in enumerate(items):
            if i == idx:
                elem_typ = t
                break
            offset += t.memory_bytes_required
        else:
            raise CompilerPanic(f"Tuple index {idx} out of range")

        elem_ptr: IROperand
        if offset == 0:
            elem_ptr = parent_ptr
        else:
            elem_ptr = b.add(parent_ptr, IRLiteral(offset))
        return elem_ptr, elem_typ

    elif isinstance(parent_typ, SArrayT):
        # Static array: key is index, element size is fixed
        elem_typ = parent_typ.value_type
        elem_size = elem_typ.memory_bytes_required

        if isinstance(key, IRLiteral):
            offset_val = key.value * elem_size
            if offset_val == 0:
                sarray_elem_ptr: IROperand = parent_ptr
            else:
                sarray_elem_ptr = b.add(parent_ptr, IRLiteral(offset_val))
        else:
            # Dynamic index
            offset_ir = b.mul(key, IRLiteral(elem_size))
            sarray_elem_ptr = b.add(parent_ptr, offset_ir)
        return sarray_elem_ptr, elem_typ

    elif isinstance(parent_typ, DArrayT):
        # Dynamic array: skip length word, then index * elem_size
        elem_typ = parent_typ.value_type
        elem_size = elem_typ.memory_bytes_required

        # Skip length word (32 bytes)
        data_ptr = b.add(parent_ptr, IRLiteral(32))

        if isinstance(key, IRLiteral):
            offset_val = key.value * elem_size
            if offset_val == 0:
                darray_elem_ptr: IROperand = data_ptr
            else:
                darray_elem_ptr = b.add(data_ptr, IRLiteral(offset_val))
        else:
            offset_ir = b.mul(key, IRLiteral(elem_size))
            darray_elem_ptr = b.add(data_ptr, offset_ir)
        return darray_elem_ptr, elem_typ

    else:
        raise CompilerPanic(f"Cannot get element ptr of type {parent_typ}")


def _zero_pad(ctx: VenomCodegenContext, bytez_ptr: IROperand) -> None:
    """
    Zero-pad a bytestring according to ABI spec.

    The bytestring at bytez_ptr has layout: [length_word][data...]
    We need to zero-pad the data to a multiple of 32 bytes.
    """
    b = ctx.builder

    # Get length
    length = b.mload(bytez_ptr)

    # dst = bytez_ptr + 32 + length (first byte after data)
    dst = b.add(bytez_ptr, IRLiteral(32))
    dst = b.add(dst, length)

    # For simplicity, write one full 32-byte zero word which handles all cases
    # since we're allowed to write past the buffer (it will be within ABI bounds)
    b.mstore(dst, IRLiteral(0))


def _encode_child(
    ctx: VenomCodegenContext,
    dst: IROperand,
    child_ptr: IROperand,
    child_typ: VyperType,
    static_ofst: int,
    dyn_ofst_val: VyperValue,
) -> None:
    """
    Encode a child element of a complex type.

    Port of _encode_child_helper from abi_encoder.py.

    Args:
        ctx: Venom codegen context
        dst: Base destination buffer
        child_ptr: Pointer to child data in memory
        child_typ: Type of child
        static_ofst: Compile-time offset in static section
        dyn_ofst_ptr: Pointer to memory variable tracking dynamic section offset
    """
    b = ctx.builder
    child_abi_t = child_typ.abi_type

    # Calculate static location
    if static_ofst == 0:
        static_loc = dst
    else:
        static_loc = b.add(dst, IRLiteral(static_ofst))

    if not child_abi_t.is_dynamic():
        # Static type: encode directly at static location
        _abi_encode_to_buf(ctx, static_loc, child_ptr, child_typ)
    else:
        # Dynamic type:
        #
        # Ordering invariant: encode child data BEFORE writing the static
        # offset word. Backend invoke-arg forwarding may pass references
        # directly, so `child_ptr` may alias the destination buffer.
        # In particular `static_loc` can point into the same region as
        # `child_ptr`. Writing the offset word first
        # would clobber source bytes that `_abi_encode_to_buf` still
        # needs to read, producing corrupt output.
        #
        # Encoding the child first is always safe: it reads from
        # `child_ptr` and writes to the dynamic section (`dst +
        # dyn_ofst`), which lies past the static section and therefore
        # cannot overlap `static_loc`.

        # 1. Read current dyn_ofst
        dyn_ofst = ctx.ptr_load(dyn_ofst_val.ptr())
        # 2. Encode child to dynamic section.
        child_dst = b.add(dst, dyn_ofst)
        child_len = _abi_encode_to_buf(ctx, child_dst, child_ptr, child_typ)

        # 3. Write static section offset (safe now — child data is already encoded).
        b.mstore(static_loc, dyn_ofst)

        # 4. Update dyn_ofst
        new_dyn_ofst = b.add(dyn_ofst, child_len)
        ctx.ptr_store(dyn_ofst_val.ptr(), new_dyn_ofst)


def _encode_dyn_array(
    ctx: VenomCodegenContext,
    dst: IROperand,
    src_ptr: IROperand,
    src_typ: DArrayT,
    dyn_ofst_val: VyperValue,
) -> None:
    """
    Encode a dynamic array.

    Port of _encode_dyn_array_helper from abi_encoder.py.

    The encoding is: [length_word] [encoded elements...]
    Where elements follow the ABI nested encoding rules.
    """
    b = ctx.builder

    subtyp = src_typ.value_type
    child_abi_t = subtyp.abi_type
    static_elem_size = child_abi_t.embedded_static_size()

    # Get runtime length
    length = b.mload(src_ptr)

    # Write length word to dst
    b.mstore(dst, length)

    # Create loop blocks (but don't switch yet - we're still in entry block)
    loop_header = b.create_block("dyn_encode_hdr")
    b.append_block(loop_header)
    loop_body = b.create_block("dyn_encode_body")
    b.append_block(loop_body)
    loop_exit = b.create_block("dyn_encode_exit")
    b.append_block(loop_exit)

    # Initialize loop counter in memory (still in entry block)
    i_val = ctx.new_temporary_value(UINT256_T)
    ctx.ptr_store(i_val.ptr(), IRLiteral(0))

    # Initialize child dynamic offset tracker if needed
    if child_abi_t.is_dynamic():
        # Start of dynamic section for children = length * static_elem_size
        child_dyn_ofst_val = ctx.new_temporary_value(UINT256_T)
        initial_child_dyn = b.mul(length, IRLiteral(static_elem_size))
        ctx.ptr_store(child_dyn_ofst_val.ptr(), initial_child_dyn)
    else:
        child_dyn_ofst_val = None

    # Jump to header and switch
    b.jmp(loop_header.label)

    # --- Loop header: check i < length ---
    b.set_block(loop_header)
    i = ctx.ptr_load(i_val.ptr())
    done = b.lt(i, length)
    done = b.iszero(done)
    b.jnz(done, loop_exit.label, loop_body.label)

    # --- Loop body ---
    b.set_block(loop_body)

    # Re-load i (we're in a new block, previous i is in different block)
    i = ctx.ptr_load(i_val.ptr())

    # Get source element pointer
    # Source elements start at src_ptr + 32 (skip length word)
    elem_size = subtyp.memory_bytes_required
    src_data = b.add(src_ptr, IRLiteral(32))
    src_offset = b.mul(i, IRLiteral(elem_size))
    child_src = b.add(src_data, src_offset)

    # Get destination element position
    # dst + 32 (skip length word) + i * static_elem_size
    dst_data = b.add(dst, IRLiteral(32))
    static_ofst = b.mul(i, IRLiteral(static_elem_size))

    if child_abi_t.is_dynamic():
        # Need to handle offset tracking
        static_loc = b.add(dst_data, static_ofst)
        assert child_dyn_ofst_val is not None
        dyn_ofst = ctx.ptr_load(child_dyn_ofst_val.ptr())
        child_dst = b.add(dst_data, dyn_ofst)
        child_len = _abi_encode_to_buf(ctx, child_dst, child_src, subtyp)

        # Preserve aliasing safety: encode child data before storing static offset.
        # If source and destination overlap, writing static_loc first can clobber
        # bytes that _abi_encode_to_buf still needs to read.
        b.mstore(static_loc, dyn_ofst)

        new_dyn_ofst = b.add(dyn_ofst, child_len)
        ctx.ptr_store(child_dyn_ofst_val.ptr(), new_dyn_ofst)
    else:
        # Static child: encode directly
        child_dst = b.add(dst_data, static_ofst)
        _abi_encode_to_buf(ctx, child_dst, child_src, subtyp)

    # Increment counter
    new_i = b.add(i, IRLiteral(1))
    ctx.ptr_store(i_val.ptr(), new_i)
    b.jmp(loop_header.label)

    # --- Exit block ---
    b.set_block(loop_exit)

    # Update parent dyn_ofst
    # Total size = 32 (length word) + final child_dyn_ofst (or length * static_size for static)
    # Note: need to reload length since we're in a new block
    length_exit = b.mload(src_ptr)
    if child_abi_t.is_dynamic():
        assert child_dyn_ofst_val is not None
        final_child_dyn = ctx.ptr_load(child_dyn_ofst_val.ptr())
        total_size = b.add(IRLiteral(32), final_child_dyn)
    else:
        # Static elements: 32 + length * static_elem_size
        total_size = b.add(IRLiteral(32), b.mul(length_exit, IRLiteral(static_elem_size)))

    parent_dyn = ctx.ptr_load(dyn_ofst_val.ptr())
    new_parent_dyn = b.add(parent_dyn, total_size)
    ctx.ptr_store(dyn_ofst_val.ptr(), new_parent_dyn)


def _abi_encode_to_buf(
    ctx: VenomCodegenContext, dst: IROperand, src: IROperand, src_typ: VyperType
) -> IROperand:
    """
    Encode src to ABI format at dst.

    Port of abi_encode() from abi_encoder.py.

    Args:
        ctx: Venom codegen context
        dst: Destination buffer pointer (in memory)
        src: Source value/pointer
        src_typ: Type of source

    Returns:
        Encoded length (dead variable elimination cleans up if unused)
    """
    b = ctx.builder
    abi_t = src_typ.abi_type

    # Fast path: if ABI encoding matches Vyper memory layout, just copy
    if abi_encoding_matches_vyper(src_typ):
        size = src_typ.memory_bytes_required
        ctx.copy_memory(dst, src, size)
        return IRLiteral(abi_t.embedded_static_size())

    # Slow path: type-specific encoding
    if src_typ._is_prim_word:
        # Primitive word type: direct copy
        val = b.mload(src)
        b.mstore(dst, val)
        return IRLiteral(32)

    elif isinstance(src_typ, _BytestringT):
        # Bytes/String: copy and zero-pad
        # Layout: [length][data]
        size = src_typ.memory_bytes_required
        ctx.copy_memory(dst, src, size)
        _zero_pad(ctx, dst)
        # ABI length = ceil32(32 + actual_length)
        length = b.mload(dst)
        padded_len = b.add(IRLiteral(32), length)
        # ceil32: ((x + 31) // 32) * 32 = (x + 31) & ~31
        padded_len = b.and_(b.add(padded_len, IRLiteral(31)), IRLiteral(~31 & ((1 << 256) - 1)))
        return padded_len

    elif isinstance(src_typ, DArrayT):
        # Dynamic array: use helper
        # Need to set up dyn_ofst tracking for parent
        dyn_ofst_val = ctx.new_temporary_value(UINT256_T)
        ctx.ptr_store(dyn_ofst_val.ptr(), IRLiteral(0))
        _encode_dyn_array(ctx, dst, src, src_typ, dyn_ofst_val)
        return ctx.ptr_load(dyn_ofst_val.ptr())

    elif _is_complex_type(src_typ):
        # Tuple/Struct/SArray: encode element by element
        if is_tuple_like(src_typ):
            items = src_typ.tuple_items()  # type: ignore[attr-defined]
        else:
            # SArrayT
            assert isinstance(src_typ, SArrayT)
            items = [(i, src_typ.value_type) for i in range(src_typ.count)]

        # Set up dynamic offset tracking if needed
        has_dynamic = abi_t.is_dynamic()
        if has_dynamic:
            dyn_ofst_val = ctx.new_temporary_value(UINT256_T)
            dyn_section_start = abi_t.static_size()
            ctx.ptr_store(dyn_ofst_val.ptr(), IRLiteral(dyn_section_start))
        else:
            dyn_ofst_val = None

        static_ofst = 0
        for idx, (key, elem_typ) in enumerate(items):
            # Get source element pointer
            if is_tuple_like(src_typ):
                elem_ptr, _ = _get_element_ptr(ctx, src, IRLiteral(idx), src_typ)
            else:
                elem_ptr, _ = _get_element_ptr(ctx, src, IRLiteral(key), src_typ)

            if has_dynamic:
                assert dyn_ofst_val is not None
                _encode_child(ctx, dst, elem_ptr, elem_typ, static_ofst, dyn_ofst_val)
            else:
                # All static, encode directly
                if static_ofst == 0:
                    child_dst = dst
                else:
                    child_dst = b.add(dst, IRLiteral(static_ofst))
                _abi_encode_to_buf(ctx, child_dst, elem_ptr, elem_typ)

            static_ofst += elem_typ.abi_type.embedded_static_size()

        if has_dynamic:
            assert dyn_ofst_val is not None
            return ctx.ptr_load(dyn_ofst_val.ptr())
        else:
            return IRLiteral(abi_t.embedded_static_size())

    else:
        raise CompilerPanic(f"Cannot ABI encode type: {src_typ}")


def abi_encode_to_buf(
    ctx: VenomCodegenContext, dst: IROperand, src: IROperand, src_typ: VyperType
) -> IROperand:
    """
    Public entry point for ABI encoding.

    Encode src to ABI format at dst.

    Args:
        ctx: Venom codegen context
        dst: Destination buffer pointer (in memory)
        src: Source value/pointer
        src_typ: Type of source

    Returns:
        Encoded length (dead variable elimination cleans up if unused)
    """
    return _abi_encode_to_buf(ctx, dst, src, src_typ)
