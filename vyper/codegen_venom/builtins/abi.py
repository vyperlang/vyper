"""
ABI encoding/decoding built-in functions.

- abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes
- abi_decode(data, output_type, unwrap_tuple=True) -> output_type
- _abi_encode, _abi_decode: deprecated aliases
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from vyper.codegen.core import calculate_type_for_external_return
from vyper.codegen_venom.abi import abi_decode_to_buf, abi_encode_to_buf
from vyper.codegen_venom.buffer import Buffer, Ptr
from vyper.codegen_venom.builtins._call import BuiltinCall, callsite
from vyper.codegen_venom.value import VyperValue
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import BytesT, TupleT
from vyper.utils import fourbytes_to_int
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _parse_method_id(method_id: Union[str, bytes, None]) -> Optional[int]:
    """Parse the method_id kwarg constant: a bytes4 hex literal (folded to
    its source string, e.g. "0xa9059cbb") or a 4-byte bytes literal."""
    if method_id is None:
        return None
    if isinstance(method_id, str):
        return fourbytes_to_int(bytes.fromhex(method_id.removeprefix("0x")))
    assert isinstance(method_id, bytes)
    return fourbytes_to_int(method_id)


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


@callsite(constant_kwargs={"ensure_tuple": True, "method_id": None})
def lower_abi_encode(call: BuiltinCall) -> VyperValue:
    """
    abi_encode(*args, ensure_tuple=True, method_id=None) -> Bytes[N]

    ABI-encode the arguments and return as a Bytes buffer.

    - ensure_tuple: If True (default), wrap single arg in tuple for ABI conformance
    - method_id: Optional 4-byte prefix (function selector)
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    ensure_tuple = call.kwarg_constants["ensure_tuple"]
    method_id = _parse_method_id(call.kwarg_constants["method_id"])

    # Primitives are stack values, complex types are memory pointers
    # (unwrap copies storage/transient to memory)
    args = call.arg_operands()
    arg_types = [arg._metadata["type"] for arg in node.args]

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


@callsite(constant_kwargs={"unwrap_tuple": True})
def lower_abi_decode(call: BuiltinCall) -> VyperValue:
    """
    abi_decode(data, output_type, unwrap_tuple=True) -> output_type

    Decode ABI-encoded data to the specified type.

    - unwrap_tuple: If True (default), single-element tuples are unwrapped
    """
    node = call.node
    ctx = call.ctx
    b = ctx.builder

    unwrap_tuple = call.kwarg_constants["unwrap_tuple"]

    # Get output type from type annotation
    output_typ = node.args[1]._metadata["type"].typedef

    # Apply tuple wrapping if needed (for ABI conformance)
    wrapped_typ = output_typ
    if unwrap_tuple:
        wrapped_typ = calculate_type_for_external_return(output_typ)

    # Get data pointer and length
    data = call.arg_operand(0)  # Copies storage/transient to memory
    assert isinstance(data, IRVariable)
    data_len = b.mload(data)  # Length word at start of Bytes
    data_ptr = b.add(data, IRLiteral(32))  # Data starts after length word

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
    hi = b.add(data_ptr, data_len)
    buf = Buffer(_ptr=data_ptr, size=wrapped_typ.memory_bytes_required, annotation="abi_decode_src")
    ptr = Ptr(operand=data_ptr, location=DataLocation.MEMORY, buf=buf)
    src = VyperValue.from_ptr(ptr, wrapped_typ)
    abi_decode_to_buf(ctx, output_val.operand, src, hi=hi)

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
