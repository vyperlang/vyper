"""
ABI encoding/decoding built-in functions.

- abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes
- abi_decode(data, output_type, unwrap_tuple=True) -> output_type
- _abi_encode, _abi_decode: deprecated aliases
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from vyper import ast as vy_ast
from vyper.codegen.core import calculate_type_for_external_return
from vyper.codegen_venom.abi import (
    abi_decode_to_buf,
    abi_encode_to_buf,
    decode_unbounded_dynarray_to_scratch,
)
from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import BytesT, TupleT, VyperType
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.infinity import type_contains_unbounded_sequence
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.semantics.types.subscriptable import DArrayT
from vyper.utils import fourbytes_to_int
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _get_kwarg_value(node: vy_ast.Call, kwarg_name: str, default=None):
    """Extract a keyword argument value from a Call node."""
    for kw in node.keywords:
        if kw.arg == kwarg_name:
            return kw.value
    return default


def _get_bool_kwarg(node: vy_ast.Call, kwarg_name: str, default: bool) -> bool:
    """Extract a boolean keyword argument (must be literal)."""
    kw_node = _get_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default
    kw_node = kw_node.reduced()
    # The value should be a NameConstant (True/False)
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    # Could also be an Int with constant value
    if isinstance(kw_node, vy_ast.Int):
        return bool(kw_node.value)
    raise CompilerPanic(f"unfoldable boolean kwarg: {kwarg_name}", kw_node)


def _parse_method_id(method_id_node: vy_ast.VyperNode) -> Optional[int]:
    """Parse method_id kwarg to integer."""
    if method_id_node is None:
        return None

    # Handle bytes literal: method_id=0xaabbccdd
    if isinstance(method_id_node, vy_ast.Hex):
        hex_val = method_id_node.value
        if isinstance(hex_val, str):
            hex_str = hex_val[2:] if hex_val.startswith("0x") else hex_val
            return fourbytes_to_int(bytes.fromhex(hex_str))
        return fourbytes_to_int(hex_val)

    # Handle bytes constant: method_id=b"\xaa\xbb\xcc\xdd"
    if isinstance(method_id_node, vy_ast.Bytes):
        return fourbytes_to_int(method_id_node.value)

    # Handle Int literal
    if isinstance(method_id_node, vy_ast.Int):
        return method_id_node.value

    # If it has a folded value (constant expression)
    if hasattr(method_id_node, "_metadata") and "folded_value" in method_id_node._metadata:
        folded = method_id_node._metadata["folded_value"]
        if isinstance(folded, vy_ast.Bytes):
            return fourbytes_to_int(folded.value)
        if isinstance(folded, vy_ast.Hex):
            hex_val = folded.value
            if isinstance(hex_val, str):
                hex_str = hex_val[2:] if hex_val.startswith("0x") else hex_val
                return fourbytes_to_int(bytes.fromhex(hex_str))

    return None


def _create_tuple_in_memory(
    ctx: VenomCodegenContext, args: list[IROperand], types: list
) -> tuple[IROperand, TupleT]:
    """Create a tuple in memory from individual args."""
    b = ctx.builder
    tuple_t = TupleT(tuple(types))
    val = ctx.new_temporary_value(tuple_t)
    assert isinstance(val.operand, IRVariable)

    offset = 0
    for arg, typ in zip(args, types):
        dst = b.add(val.operand, IRLiteral(offset))

        if typ._is_prim_word:
            b.mstore(dst, arg)
        else:
            ctx.copy_memory(dst, arg, typ.memory_bytes_required)

        offset += typ.memory_bytes_required

    return val.operand, tuple_t


def _runtime_abi_size_for_arg(ctx: VenomCodegenContext, arg_vv: VyperValue) -> IROperand:
    typ = arg_vv.typ
    if isinstance(typ, _BytestringT):
        ptr = ctx.unwrap(arg_vv)
        assert isinstance(ptr, IRVariable)
        return ctx.bytestring_runtime_size(ptr)
    if isinstance(typ, DArrayT) and ctx.is_unbounded_dynarray_type(typ):
        ptr = ctx.unwrap(arg_vv)
        assert isinstance(ptr, IRVariable)
        return ctx.dynarray_runtime_abi_size(ptr, typ)
    return IRLiteral(typ.abi_type.size_bound())


def _runtime_abi_size_for_encode(
    ctx: VenomCodegenContext, arg_vals: list[VyperValue], encode_type: VyperType
) -> IROperand:
    if isinstance(encode_type, TupleT):
        size: IROperand = IRLiteral(encode_type.abi_type.static_size())
        for arg_vv in arg_vals:
            if arg_vv.typ.abi_type.is_dynamic():
                size = ctx.checked_add(size, _runtime_abi_size_for_arg(ctx, arg_vv))
        return size

    return _runtime_abi_size_for_arg(ctx, arg_vals[0])


def _abi_encode_values_to_buf(
    ctx: VenomCodegenContext, dst: IRVariable, arg_vals: list[VyperValue], encode_type: VyperType
) -> IROperand:
    b = ctx.builder

    if not isinstance(encode_type, TupleT):
        src = ctx.unwrap(arg_vals[0])
        assert isinstance(src, IRVariable)
        return abi_encode_to_buf(ctx, dst, src, encode_type)

    dyn_ofst_val = ctx.new_temporary_value(UINT256_T)
    ctx.ptr_store(dyn_ofst_val.ptr(), IRLiteral(encode_type.abi_type.static_size()))

    static_ofst = 0
    for arg_vv in arg_vals:
        typ = arg_vv.typ
        static_loc = b.add(dst, IRLiteral(static_ofst))

        if typ.abi_type.is_dynamic():
            dyn_ofst = ctx.ptr_load(dyn_ofst_val.ptr())
            child_dst = b.add(dst, dyn_ofst)
            child_src = ctx.unwrap(arg_vv)
            assert isinstance(child_src, IRVariable)
            child_len = abi_encode_to_buf(ctx, child_dst, child_src, typ)
            b.mstore(static_loc, dyn_ofst)
            ctx.ptr_store(dyn_ofst_val.ptr(), ctx.checked_add(dyn_ofst, child_len))
        else:
            ctx.store_vyper_value(arg_vv, static_loc, typ)

        static_ofst += typ.abi_type.embedded_static_size()

    return ctx.ptr_load(dyn_ofst_val.ptr())


def _decode_unbounded_bytestring_from_abi(
    ctx: VenomCodegenContext, src: IRVariable, hi: IROperand, typ: VyperType
) -> VyperValue:
    b = ctx.builder
    assert ctx.is_unbounded_bytestring_type(typ)

    length = b.mload(src)
    ctx.assert_abi_bytes_payload_in_bounds(src, length, hi)

    data_start = b.add(src, IRLiteral(32))
    return ctx.materialize_bytes_from_location(
        data_start, length, typ, DataLocation.MEMORY, annotation="abi_decode"
    )


def _decode_unbounded_sequence_from_abi(
    ctx: VenomCodegenContext, src: IRVariable, hi: IROperand, typ: VyperType
) -> VyperValue:
    if ctx.is_unbounded_bytestring_type(typ):
        return _decode_unbounded_bytestring_from_abi(ctx, src, hi, typ)

    if isinstance(typ, DArrayT) and ctx.is_unbounded_dynarray_type(typ):
        src_vv = VyperValue.from_ptr(
            Ptr(
                operand=src,
                location=DataLocation.MEMORY,
                buf=Buffer(_ptr=src, size=None, annotation="abi_decode_src"),
            ),
            typ,
        )
        return decode_unbounded_dynarray_to_scratch(ctx, src_vv, typ, hi, "abi_decode")

    raise CompilerPanic(f"expected unbounded sequence type, got {typ}")  # pragma: nocover


def lower_abi_encode(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes[N]

    ABI-encode the arguments and return as a Bytes buffer.

    - ensure_tuple: If True (default), wrap single arg in tuple for ABI conformance
    - method_id: Optional 4-byte prefix (function selector)
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    # Parse kwargs
    ensure_tuple = _get_bool_kwarg(node, "ensure_tuple", default=True)
    method_id_node = _get_kwarg_value(node, "method_id")
    method_id = _parse_method_id(method_id_node)

    arg_types = [arg._metadata["type"] for arg in node.args]
    if any(type_contains_unbounded_sequence(t) for t in arg_types):
        arg_vals = [Expr(arg, ctx).lower() for arg in node.args]
        if len(arg_vals) == 1 and not ensure_tuple:
            encode_type: VyperType = arg_types[0]
        else:
            encode_type = TupleT(tuple(arg_types))

        encoded_size = _runtime_abi_size_for_encode(ctx, arg_vals, encode_type)
        alloc_size = encoded_size
        if method_id is not None:
            alloc_size = ctx.checked_add(alloc_size, IRLiteral(4))

        buf_ptr = ctx.allocate_scratch(ctx.checked_add(alloc_size, IRLiteral(32)))
        # Safe margin: buf is exactly `[length word] + alloc_size`, and the
        # padding zero write lands at `buf_ptr + ceil32(alloc_size)`.
        ctx.zero_bytestring_padding(buf_ptr, alloc_size)

        if method_id is not None:
            method_id_word = method_id << 224
            b.mstore(b.add(buf_ptr, IRLiteral(32)), IRLiteral(method_id_word))
            data_dst = b.add(buf_ptr, IRLiteral(36))
            encoded_len = _abi_encode_values_to_buf(ctx, data_dst, arg_vals, encode_type)
            total_len = ctx.checked_add(encoded_len, IRLiteral(4))
            b.mstore(buf_ptr, total_len)
        else:
            data_dst = b.add(buf_ptr, IRLiteral(32))
            encoded_len = _abi_encode_values_to_buf(ctx, data_dst, arg_vals, encode_type)
            b.mstore(buf_ptr, encoded_len)

        return ctx.dynamic_memory_value(buf_ptr, node._metadata["type"], annotation="abi_encode")

    # Evaluate all args - primitives get values, complex types get pointers
    args = []
    for arg in node.args:
        arg_t = arg._metadata["type"]
        if arg_t._is_prim_word:
            args.append(Expr(arg, ctx).lower_value())
        else:
            arg_vv = Expr(arg, ctx).lower()
            args.append(ctx.unwrap(arg_vv))  # Copies storage/transient to memory

    # Build input to encode
    if len(args) == 1 and not ensure_tuple:
        # Single arg without tuple wrapping
        if arg_types[0]._is_prim_word:
            # abi_encode_to_buf expects a memory pointer, not a value.
            # Store the value to a temporary memory location.
            tmp = ctx.new_temporary_value(arg_types[0])
            assert isinstance(tmp.operand, IRVariable)
            b.mstore(tmp.operand, args[0])
            encode_input: IROperand = tmp.operand
        else:
            encode_input = args[0]
        encode_type = arg_types[0]
    else:
        # Create tuple from args
        encode_input, encode_type = _create_tuple_in_memory(ctx, args, arg_types)

    # Calculate buffer size
    maxlen = encode_type.abi_type.size_bound()
    if method_id is not None:
        maxlen += 4

    # Allocate output buffer: [32-byte length] | [optional 4-byte method_id] | [data]
    buf_t = BytesT(maxlen)
    buf_val = ctx.new_temporary_value(buf_t)
    assert isinstance(buf_val.operand, IRVariable)

    if method_id is not None:
        # Write method_id at offset 32 (start of data area, after 32-byte length field)
        # method_id is 4 bytes, so shift left by 28 bytes = 224 bits
        method_id_word = method_id << 224
        b.mstore(b.add(buf_val.operand, IRLiteral(32)), IRLiteral(method_id_word))

        # Encode data starting at offset 36
        data_dst = b.add(buf_val.operand, IRLiteral(36))
        encoded_len = abi_encode_to_buf(ctx, data_dst, encode_input, encode_type)

        # Write total length (encoded_len + 4) at offset 0
        total_len = b.add(encoded_len, IRLiteral(4))
        b.mstore(buf_val.operand, total_len)
    else:
        # Encode data starting at offset 32
        data_dst = b.add(buf_val.operand, IRLiteral(32))
        encoded_len = abi_encode_to_buf(ctx, data_dst, encode_input, encode_type)

        # Write length at offset 0
        b.mstore(buf_val.operand, encoded_len)

    return buf_val


def lower_abi_decode(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    abi_decode(data, output_type, unwrap_tuple=True) -> output_type

    Decode ABI-encoded data to the specified type.

    - unwrap_tuple: If True (default), single-element tuples are unwrapped
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    # Parse args
    data_node = node.args[0]
    output_type_node = node.args[1]
    unwrap_tuple = _get_bool_kwarg(node, "unwrap_tuple", default=True)

    # Get output type from type annotation
    output_typ = output_type_node._metadata["type"].typedef

    # Apply tuple wrapping if needed (for ABI conformance)
    wrapped_typ = output_typ
    if unwrap_tuple:
        wrapped_typ = calculate_type_for_external_return(output_typ)

    # Get data pointer and length
    data_vv = Expr(data_node, ctx).lower()
    data = ctx.unwrap(data_vv)  # Copies storage/transient to memory
    assert isinstance(data, IRVariable)
    data_len = b.mload(data)  # Length word at start of Bytes
    data_ptr = b.add(data, IRLiteral(32))  # Data starts after length word
    hi = b.add(data_ptr, data_len)
    no_hi_wrap = b.iszero(b.lt(hi, data_ptr))
    b.assert_(no_hi_wrap)

    if ctx.is_unbounded_sequence_type(output_typ):
        if unwrap_tuple:
            abi_min_size = wrapped_typ.abi_type.static_size()
            ge_min = b.iszero(b.lt(data_len, IRLiteral(abi_min_size)))
            b.assert_(ge_min)

            offset = b.mload(data_ptr)
            src = b.add(data_ptr, offset)
            no_src_wrap = b.iszero(b.lt(src, data_ptr))
            b.assert_(no_src_wrap)
            return _decode_unbounded_sequence_from_abi(ctx, src, hi, output_typ)

        ge_length_word = b.iszero(b.lt(data_len, IRLiteral(32)))
        b.assert_(ge_length_word)
        return _decode_unbounded_sequence_from_abi(ctx, data_ptr, hi, output_typ)

    # Validate size
    abi_min_size = wrapped_typ.abi_type.static_size()
    abi_max_size = wrapped_typ.abi_type.size_bound()

    if abi_min_size == abi_max_size:
        # Fixed size: assert exact match
        b.assert_(b.eq(data_len, IRLiteral(abi_min_size)))
    else:
        # Variable size: assert min <= len <= max
        # ge(a, b) = iszero(lt(a, b))
        # le(a, b) = iszero(gt(a, b))
        ge_min = b.iszero(b.lt(data_len, IRLiteral(abi_min_size)))
        le_max = b.iszero(b.gt(data_len, IRLiteral(abi_max_size)))
        b.assert_(b.and_(ge_min, le_max))

    # Allocate output buffer
    output_val = ctx.new_temporary_value(wrapped_typ)
    assert isinstance(output_val.operand, IRVariable)

    # Decode with bounds checking
    buf = Buffer(_ptr=data_ptr, size=wrapped_typ.memory_bytes_required, annotation="abi_decode_src")
    ptr = Ptr(operand=data_ptr, location=DataLocation.MEMORY, buf=buf)
    src_vv = VyperValue.from_ptr(ptr, wrapped_typ)
    abi_decode_to_buf(ctx, output_val.operand, src_vv, hi=hi)

    # Return with output_typ (unwrapped type if applicable)
    if unwrap_tuple and wrapped_typ != output_typ:
        # For single-element tuple, element 0 is at offset 0
        return VyperValue.from_ptr(output_val.ptr(), output_typ)
    return output_val


HANDLERS = {
    "abi_encode": lower_abi_encode,
    "abi_decode": lower_abi_decode,
    "_abi_encode": lower_abi_encode,  # deprecated alias
    "_abi_decode": lower_abi_decode,  # deprecated alias
}
