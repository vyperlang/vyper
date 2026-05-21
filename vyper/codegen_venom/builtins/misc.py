"""
Miscellaneous built-in functions.

- ecrecover, ecadd, ecmul: Elliptic curve precompiles
- blockhash, blobhash: Block info
- floor, ceil: Decimal truncation
- as_wei_value: Wei denomination conversion
- min_value, max_value, epsilon: Compile-time constants
- breakpoint: Debug interrupt
- print: Debug logging to console.log address
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.builtins.functions import AsWeiValue
from vyper.codegen_venom.abi.abi_encoder import abi_encode_to_buf
from vyper.codegen_venom.constants import BLOCKHASH_LOOKBACK_LIMIT, ECRECOVER_PRECOMPILE
from vyper.evm.opcodes import version_check
from vyper.exceptions import EvmVersionException
from vyper.semantics.types import BytesT, DecimalT, StringT, TupleT
from vyper.utils import DECIMAL_DIVISOR, method_id_int
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


# Console.log address used by debugging tools
CONSOLE_ADDRESS = 0x000000000000000000636F6E736F6C652E6C6F67


# =============================================================================
# Elliptic Curve Precompiles
# =============================================================================


def lower_ecrecover(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    ecrecover(hash, v, r, s) -> address

    Recovers signer address from ECDSA signature via precompile 0x1.
    Input: 128 bytes (hash, v, r, s)
    Output: 32 bytes (address, right-padded)
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    hash_val = Expr(node.args[0], ctx).lower_value()
    v = Expr(node.args[1], ctx).lower_value()
    r = Expr(node.args[2], ctx).lower_value()
    s = Expr(node.args[3], ctx).lower_value()

    # Prepare input buffer (128 bytes)
    input_buf = ctx.allocate_buffer(128)
    b.mstore(input_buf._ptr, hash_val)
    b.mstore(b.add(input_buf._ptr, IRLiteral(32)), v)
    b.mstore(b.add(input_buf._ptr, IRLiteral(64)), r)
    b.mstore(b.add(input_buf._ptr, IRLiteral(96)), s)

    # Output buffer (32 bytes) - clear first since ecrecover may return 0 bytes
    output_buf = ctx.allocate_buffer(32)
    b.mstore(output_buf._ptr, IRLiteral(0))

    # Call ecrecover precompile
    success = b.staticcall(
        b.gas(),
        IRLiteral(ECRECOVER_PRECOMPILE),
        input_buf._ptr,
        IRLiteral(128),
        output_buf._ptr,
        IRLiteral(32),
    )
    b.assert_(success)

    return b.mload(output_buf._ptr)


def lower_ecadd(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    ecadd(a, b) -> uint256[2]

    BN256 point addition via precompile 0x6.
    Input: 128 bytes (x1, y1, x2, y2)
    Output: 64 bytes (x, y)
    """
    return _lower_ec_arith(node, ctx, precompile=6)


def lower_ecmul(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    ecmul(point, scalar) -> uint256[2]

    BN256 scalar multiplication via precompile 0x7.
    Input: 96 bytes (x, y, scalar)
    Output: 64 bytes (x, y)
    """
    return _lower_ec_arith(node, ctx, precompile=7)


def _lower_ec_arith(node: vy_ast.Call, ctx: VenomCodegenContext, precompile: int) -> IROperand:
    """
    Common implementation for ecadd/ecmul.

    Both return a uint256[2] stored in memory.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    # Get argument types to determine input size
    # ecadd: (uint256[2], uint256[2]) = 128 bytes
    # ecmul: (uint256[2], uint256) = 96 bytes
    args_typ = [arg._metadata["type"] for arg in node.args]
    input_size = sum(t.memory_bytes_required for t in args_typ)

    # CRITICAL: Evaluate ALL arguments FIRST before any copying.
    # This ensures correct evaluation order when arguments have side effects
    # (e.g., ecadd(self.x, self.bar()) where bar() modifies self.x).
    # For arrays from storage/transient, unwrap() copies them to memory first.
    evaluated_args = []
    for arg in node.args:
        arg_typ = arg._metadata["type"]
        if arg_typ._is_prim_word:
            # Primitive: get value directly
            evaluated_args.append(Expr(arg, ctx).lower_value())
        else:
            # Array: unwrap handles storage/transient/code -> memory conversion
            arg_vv = Expr(arg, ctx).lower()
            evaluated_args.append(ctx.unwrap(arg_vv))

    # Now copy evaluated arguments to input buffer
    input_buf = ctx.allocate_buffer(input_size)
    offset = 0
    for i, arg_typ in enumerate(args_typ):
        arg_val = evaluated_args[i]

        if arg_typ._is_prim_word:
            # Single 32-byte value
            b.mstore(b.add(input_buf._ptr, IRLiteral(offset)), arg_val)
            offset += 32
        else:
            # Array (uint256[2]) - arg_val is now a memory pointer
            for j in range(arg_typ.count):
                word = b.mload(b.add(arg_val, IRLiteral(j * 32)))
                b.mstore(b.add(input_buf._ptr, IRLiteral(offset)), word)
                offset += 32

    # Output buffer (64 bytes for resulting point)
    output_buf = ctx.allocate_buffer(64)

    # Call precompile
    success = b.staticcall(
        b.gas(),
        IRLiteral(precompile),
        input_buf._ptr,
        IRLiteral(input_size),
        output_buf._ptr,
        IRLiteral(64),
    )
    b.assert_(success)

    # Return pointer to output buffer (it's a memory location with the result array)
    return output_buf._ptr


# =============================================================================
# Block Info
# =============================================================================


def lower_blockhash(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    blockhash(block_num) -> bytes32

    Returns block hash for given block number.
    Only works for the 256 most recent blocks (excluding current).
    Reverts if block_num is out of valid range.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    block_num = Expr(node.args[0], ctx).lower_value()

    # Validate block number is in valid range:
    # block_num >= block.number - BLOCKHASH_LOOKBACK_LIMIT AND block_num < block.number
    # The legacy code uses clamp("lt", clamp("sge", x, lower), "number")
    # which asserts (reverts if false) both conditions.
    current_block = b.number()
    lower_bound = b.sub(current_block, IRLiteral(BLOCKHASH_LOOKBACK_LIMIT))

    # Assert block_num >= lower_bound (signed comparison)
    # sge(a, b) = not slt(a, b)
    is_ge_lower = b.iszero(b.slt(block_num, lower_bound))
    b.assert_(is_ge_lower)

    # Assert block_num < current_block
    is_lt_current = b.lt(block_num, current_block)
    b.assert_(is_lt_current)

    return b.blockhash(block_num)


def lower_blobhash(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    blobhash(index) -> bytes32

    Returns versioned hash of blob at given index (Cancun+).
    """
    from vyper.codegen_venom.expr import Expr

    if not version_check(begin="cancun"):
        raise EvmVersionException("`blobhash` is not available pre-cancun", node)

    b = ctx.builder

    index = Expr(node.args[0], ctx).lower_value()
    return b.blobhash(index)


# =============================================================================
# Decimal Truncation
# =============================================================================


def lower_floor(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    floor(x) -> int256

    Truncates decimal toward negative infinity.
    For positive: x / divisor
    For negative: (x - (divisor - 1)) / divisor
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    val = Expr(node.args[0], ctx).lower_value()
    divisor = IRLiteral(DECIMAL_DIVISOR)

    # For negative values: subtract (divisor - 1) before dividing
    # This makes sdiv round toward -infinity instead of toward 0
    is_negative = b.slt(val, IRLiteral(0))
    adjusted = b.sub(val, IRLiteral(DECIMAL_DIVISOR - 1))
    adjusted_or_orig = b.select(is_negative, adjusted, val)

    return b.sdiv(adjusted_or_orig, divisor)


def lower_ceil(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    ceil(x) -> int256

    Truncates decimal toward positive infinity.
    For positive: (x + (divisor - 1)) / divisor
    For negative: x / divisor
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    val = Expr(node.args[0], ctx).lower_value()
    divisor = IRLiteral(DECIMAL_DIVISOR)

    # For positive values: add (divisor - 1) before dividing
    # This makes sdiv round toward +infinity
    is_negative = b.slt(val, IRLiteral(0))
    adjusted = b.add(val, IRLiteral(DECIMAL_DIVISOR - 1))
    adjusted_or_orig = b.select(is_negative, val, adjusted)

    return b.sdiv(adjusted_or_orig, divisor)


# =============================================================================
# Wei Denomination
# =============================================================================


def lower_as_wei_value(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    as_wei_value(value, unit) -> uint256

    Converts a value to wei based on denomination unit.
    Includes overflow check for the multiplication.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    value = Expr(node.args[0], ctx).lower_value()
    typ = node.args[0]._metadata["type"]

    # Get the denomination multiplier
    denom = AsWeiValue().get_denomination(node)

    if denom == 1:
        # No multiplication needed for "wei"
        if isinstance(typ, DecimalT):
            # Decimal case: check non-negative and divide by DECIMAL_DIVISOR
            is_non_negative = b.iszero(b.slt(value, IRLiteral(0)))
            b.assert_(is_non_negative)
            return b.div(value, IRLiteral(DECIMAL_DIVISOR))
        else:
            return value

    if isinstance(typ, DecimalT):
        # Decimal: check non-negative, multiply, then divide by DECIMAL_DIVISOR
        # This maintains precision: (value * denom) / DECIMAL_DIVISOR
        is_non_negative = b.iszero(b.slt(value, IRLiteral(0)))
        b.assert_(is_non_negative)
        product = b.mul(value, IRLiteral(denom))
        return b.div(product, IRLiteral(DECIMAL_DIVISOR))

    # Integer case: value * denom with overflow check
    product = b.mul(value, IRLiteral(denom))

    # Overflow check: (product / value == denom) || value == 0
    quotient = b.div(product, value)
    is_safe_div = b.eq(quotient, IRLiteral(denom))
    is_zero = b.iszero(value)
    is_ok = b.or_(is_safe_div, is_zero)

    if typ.is_signed:
        # For signed types, also check value >= 0
        is_positive = b.iszero(b.slt(value, IRLiteral(0)))
        is_ok = b.and_(is_positive, is_ok)

    b.assert_(is_ok)

    return product


# =============================================================================
# Compile-time Type Constants
# =============================================================================


def lower_min_value(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    min_value(T) -> T

    Returns the minimum value for a numeric type.
    This is evaluated at compile time.
    """
    typ = node.args[0]._metadata["type"].typedef
    return IRLiteral(typ.ast_bounds[0])


def lower_max_value(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    max_value(T) -> T

    Returns the maximum value for a numeric type.
    This is evaluated at compile time.
    """
    typ = node.args[0]._metadata["type"].typedef
    return IRLiteral(typ.ast_bounds[1])


def lower_epsilon(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    epsilon(decimal) -> decimal

    Returns the smallest positive decimal value (10^-10).
    """
    # The smallest decimal unit is 1 (representing 10^-10)
    return IRLiteral(1)


# =============================================================================
# Debug
# =============================================================================


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
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value
    if isinstance(kw_node, vy_ast.Int):
        return bool(kw_node.value)
    return default


def _create_tuple_in_memory(
    ctx: "VenomCodegenContext", args: list[IROperand], types: list
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


def lower_print(node: vy_ast.Call, ctx: "VenomCodegenContext") -> IROperand:
    """
    print(*args, hardhat_compat=False) -> None

    Debug printing via staticcall to console.log address.

    In default mode (hardhat_compat=False):
    - Uses method_id("log(string,bytes)")
    - First arg is type schema string (e.g. "(uint256,address)")
    - Second arg is ABI-encoded args as bytes

    In hardhat_compat mode:
    - Uses method_id("log(type1,type2,...)") directly
    - Args are ABI-encoded inline
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    hardhat_compat = _get_bool_kwarg(node, "hardhat_compat", default=False)

    # Get arg types and values
    arg_types = [arg._metadata["type"] for arg in node.args]

    # Evaluate all args - primitives get values, complex types get pointers
    args = []
    for arg in node.args:
        arg_t = arg._metadata["type"]
        if arg_t._is_prim_word:
            args.append(Expr(arg, ctx).lower_value())
        else:
            arg_vv = Expr(arg, ctx).lower()
            args.append(ctx.unwrap(arg_vv))  # Copies storage/transient to memory

    # Create tuple type for ABI encoding
    tuple_t = TupleT(tuple(arg_types))
    args_abi_t = tuple_t.abi_type

    # Generate signature like "log(uint256,address)"
    sig = "log(" + ",".join([t.abi_type.selector_name() for t in arg_types]) + ")"

    if hardhat_compat:
        # Direct encoding with the actual type signature
        mid = method_id_int(sig)
        buflen = 32 + args_abi_t.size_bound()

        # Allocate buffer: [32 bytes padding for method_id alignment] | [data]
        buf = ctx.allocate_buffer(buflen)

        # Store method_id at buf (shifted left to align in word)
        method_id_word = mid << 224
        b.mstore(buf._ptr, IRLiteral(method_id_word))

        # Create tuple in memory and encode starting at buf + 32
        if len(args) > 0:
            encode_input, encode_type = _create_tuple_in_memory(ctx, args, arg_types)
            data_dst = b.add(buf._ptr, IRLiteral(32))
            encoded_len = abi_encode_to_buf(ctx, data_dst, encode_input, encode_type)
        else:
            encoded_len = IRLiteral(0)

        # staticcall(gas, CONSOLE_ADDRESS, buf+28, 4+encoded_len, 0, 0)
        # buf+28 positions the 4-byte method_id at the start of calldata
        call_start = b.add(buf._ptr, IRLiteral(28))
        call_len = b.add(IRLiteral(4), encoded_len)

    else:
        # Default mode: log(string,bytes) format
        # First encode the args as bytes payload
        mid = method_id_int("log(string,bytes)")

        # Schema is the ABI type selector, e.g. "(uint256,address)"
        schema = args_abi_t.selector_name().encode("utf-8")
        schema_len = len(schema)

        # Encode the args to a bytes payload first
        payload_buflen = args_abi_t.size_bound()

        # Allocate payload buffer: [32 bytes length] | [data]
        payload_buf = ctx.allocate_buffer(32 + payload_buflen)

        if len(args) > 0:
            encode_input, encode_type = _create_tuple_in_memory(ctx, args, arg_types)
            payload_data_dst = b.add(payload_buf._ptr, IRLiteral(32))
            payload_len = abi_encode_to_buf(ctx, payload_data_dst, encode_input, encode_type)
        else:
            payload_len = IRLiteral(0)

        # Store payload length
        b.mstore(payload_buf._ptr, payload_len)

        # Allocate schema buffer: [32 bytes length] | [data]
        schema_buf = ctx.allocate_buffer(32 + schema_len)
        b.mstore(schema_buf._ptr, IRLiteral(schema_len))

        # Write schema string bytes (word by word)
        schema_data_ptr = b.add(schema_buf._ptr, IRLiteral(32))
        for i in range(0, schema_len, 32):
            chunk = schema[i : i + 32]
            # Pad chunk to 32 bytes (left-aligned in word)
            chunk_padded = chunk.ljust(32, b"\x00")
            chunk_int = int.from_bytes(chunk_padded, "big")
            b.mstore(b.add(schema_data_ptr, IRLiteral(i)), IRLiteral(chunk_int))

        # Now encode (schema_string, payload_bytes) as a tuple
        schema_t = StringT(schema_len)
        payload_t = BytesT(payload_buflen)
        outer_tuple_t = TupleT((schema_t, payload_t))

        # Create tuple in memory with pointers to schema and payload buffers
        outer_val = ctx.new_temporary_value(outer_tuple_t)
        assert isinstance(outer_val.operand, IRVariable)
        ctx.copy_memory(outer_val.operand, schema_buf._ptr, schema_t.memory_bytes_required)
        dst_payload = b.add(outer_val.operand, IRLiteral(schema_t.memory_bytes_required))
        ctx.copy_memory(dst_payload, payload_buf._ptr, payload_t.memory_bytes_required)

        # Allocate final output buffer for ABI encoding
        outer_abi_size = outer_tuple_t.abi_type.size_bound()
        final_buflen = 32 + outer_abi_size
        buf = ctx.allocate_buffer(final_buflen)

        # Store method_id
        method_id_word = mid << 224
        b.mstore(buf._ptr, IRLiteral(method_id_word))

        # Encode outer tuple
        data_dst = b.add(buf._ptr, IRLiteral(32))
        encoded_len = abi_encode_to_buf(ctx, data_dst, outer_val.operand, outer_tuple_t)

        call_start = b.add(buf._ptr, IRLiteral(28))
        call_len = b.add(IRLiteral(4), encoded_len)

    # Make the staticcall to console.log
    retptr = ctx.allocate_buffer(0)
    b.staticcall(
        b.gas(), IRLiteral(CONSOLE_ADDRESS), call_start, call_len, retptr._ptr, IRLiteral(0)
    )

    return IRLiteral(0)


def lower_breakpoint(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    breakpoint() -> None

    Inserts an INVALID opcode for debugging.
    """
    ctx.builder.invalid()
    return IRLiteral(0)


# Export handlers
HANDLERS = {
    "ecrecover": lower_ecrecover,
    "ecadd": lower_ecadd,
    "ecmul": lower_ecmul,
    "blockhash": lower_blockhash,
    "blobhash": lower_blobhash,
    "floor": lower_floor,
    "ceil": lower_ceil,
    "as_wei_value": lower_as_wei_value,
    "min_value": lower_min_value,
    "max_value": lower_max_value,
    "epsilon": lower_epsilon,
    "breakpoint": lower_breakpoint,
    "print": lower_print,
}
