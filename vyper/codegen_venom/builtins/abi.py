"""
ABI encoding/decoding built-in functions.

- abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes
- abi_decode(data, output_type, unwrap_tuple=True) -> output_type
- _abi_encode, _abi_decode: deprecated aliases
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from vyper import ast as vy_ast
from vyper.codegen.core import calculate_type_for_external_return
from vyper.codegen_venom.abi import (
    abi_decode_to_buf,
    abi_encode_values_to_buf,
    decode_unbounded_sequence_to_scratch,
    runtime_abi_size_for_encode,
)
from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.eval_order import later_expressions_can_mutate_memory_or_storage
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic, StructureException
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import BytesT, TupleT, VyperType
from vyper.semantics.types.infinity import type_contains_unbounded_sequence
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


def _finish_abi_encoded_bytes(
    ctx: VenomCodegenContext,
    buf_ptr: IRVariable,
    method_id: Optional[int],
    encode_fn: Callable[[IRVariable], IROperand],
    add_fn: Callable[[IROperand, IROperand], IROperand],
    zero_tail_padding: bool = False,
) -> None:
    b = ctx.builder
    if method_id is not None:
        # Bytes layout is [length][payload]. method_id occupies payload[0:4],
        # so the ABI payload begins at byte 36.
        method_id_word = method_id << 224
        b.mstore(b.add(buf_ptr, IRLiteral(32)), IRLiteral(method_id_word))
        data_dst = b.add(buf_ptr, IRLiteral(36))
        encoded_len = encode_fn(data_dst)
        if zero_tail_padding:
            # encoded_len is a word multiple, so with the 4-byte method_id
            # prefix the value's last word spans [buf+32+encoded_len,
            # buf+64+encoded_len): 4 data bytes followed by 28 padding bytes
            # of scratch memory. Zero the padding bytes; they can hold stale
            # data when the allocation size over-estimated encoded_len.
            last_word_ptr = b.add(b.add(buf_ptr, IRLiteral(32)), encoded_len)
            keep_data_mask = IRLiteral(((1 << 32) - 1) << 224)
            b.mstore(last_word_ptr, b.and_(b.mload(last_word_ptr), keep_data_mask))
        total_len = add_fn(encoded_len, IRLiteral(4))
        b.mstore(buf_ptr, total_len)
    else:
        data_dst = b.add(buf_ptr, IRLiteral(32))
        encoded_len = encode_fn(data_dst)
        b.mstore(buf_ptr, encoded_len)


def lower_abi_encode(node: vy_ast.Call, ctx: VenomCodegenContext) -> VyperValue:
    """
    abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes[N]

    ABI-encode the arguments and return as a Bytes buffer.

    - ensure_tuple: If True (default), wrap single arg in tuple for ABI conformance
    - method_id: Optional 4-byte prefix (function selector)
    """
    from vyper.codegen_venom.expr import Expr

    if len(node.args) < 1:
        raise StructureException("abi_encode expects at least one argument", node)

    b = ctx.builder

    # Parse kwargs
    ensure_tuple = _get_bool_kwarg(node, "ensure_tuple", default=True)
    method_id_node = _get_kwarg_value(node, "method_id")
    method_id = _parse_method_id(method_id_node)

    arg_types = [arg._metadata["type"] for arg in node.args]
    arg_vals = []
    for i, arg in enumerate(node.args):
        arg_vv = Expr(arg, ctx).lower()
        copy_composites = later_expressions_can_mutate_memory_or_storage(node.args[i + 1 :])
        arg_vals.append(
            ctx.snapshot_value_for_delayed_use(
                arg_vv, annotation="abi_encode", copy_composites=copy_composites
            )
        )

    if len(arg_vals) == 1 and not ensure_tuple:
        encode_type: VyperType = arg_types[0]
    else:
        encode_type = TupleT(tuple(arg_types))

    if any(type_contains_unbounded_sequence(t) for t in arg_types):
        encoded_size = runtime_abi_size_for_encode(ctx, arg_vals, encode_type)
        alloc_size = encoded_size
        if method_id is not None:
            alloc_size = ctx.checked_add(alloc_size, IRLiteral(4))

        buf_ptr = ctx.allocate_scratch(ctx.checked_add(alloc_size, IRLiteral(32)))
        if method_id is None:
            # Safe margin: buf is exactly `[length word] + alloc_size`, and the
            # padding zero write lands at `buf_ptr + ceil32(alloc_size)`.
            #
            # With method_id, `alloc_size` can over-estimate the runtime
            # encoded length (bounded dynamic args are sized by their bound),
            # so this write can land past the value's actual last word;
            # _finish_abi_encoded_bytes zeroes the tail padding instead.
            ctx.zero_bytestring_padding(buf_ptr, alloc_size)

        def encode_unbounded(dst: IRVariable) -> IROperand:
            return abi_encode_values_to_buf(ctx, dst, arg_vals, encode_type)

        _finish_abi_encoded_bytes(
            ctx, buf_ptr, method_id, encode_unbounded, ctx.checked_add, zero_tail_padding=True
        )

        return ctx.dynamic_memory_value(buf_ptr, node._metadata["type"], annotation="abi_encode")

    # Calculate buffer size
    maxlen = encode_type.abi_type.size_bound()
    if method_id is not None:
        maxlen += 4

    # Allocate output buffer: [32-byte length] | [optional 4-byte method_id] | [data]
    buf_t = BytesT(maxlen)
    buf_val = ctx.new_temporary_value(buf_t)
    assert isinstance(buf_val.operand, IRVariable)

    def encode_bounded(dst: IRVariable) -> IROperand:
        return abi_encode_values_to_buf(ctx, dst, arg_vals, encode_type)

    _finish_abi_encoded_bytes(ctx, buf_val.operand, method_id, encode_bounded, b.add)

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

    if ctx.is_unbounded_sequence_type(output_typ):
        no_hi_wrap = b.iszero(b.lt(hi, data_ptr))
        b.assert_(no_hi_wrap)

        if unwrap_tuple:
            abi_min_size = wrapped_typ.abi_type.static_size()
            ge_min = b.iszero(b.lt(data_len, IRLiteral(abi_min_size)))
            b.assert_(ge_min)

            offset = b.mload(data_ptr)
            src = b.add(data_ptr, offset)
            no_src_wrap = b.iszero(b.lt(src, data_ptr))
            b.assert_(no_src_wrap)
            return decode_unbounded_sequence_to_scratch(ctx, src, output_typ, hi, "abi_decode")

        ge_length_word = b.iszero(b.lt(data_len, IRLiteral(32)))
        b.assert_(ge_length_word)
        return decode_unbounded_sequence_to_scratch(ctx, data_ptr, output_typ, hi, "abi_decode")

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
