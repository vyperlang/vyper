"""
Miscellaneous built-in functions.

- ecrecover, ecadd, ecmul: Elliptic curve precompiles
- blockhash, blobhash: Block info
- floor, ceil: Decimal truncation
- as_wei_value: Wei denomination conversion
- min_value, max_value, epsilon: Compile-time constants
- isqrt: Integer square root
- breakpoint: Debug interrupt
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.codegen_venom.constants import BLOCKHASH_LOOKBACK_LIMIT, ECRECOVER_PRECOMPILE
from vyper.semantics.types import DecimalT
from vyper.utils import DECIMAL_DIVISOR
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


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

    # Allocate input buffer and store arguments
    input_buf = ctx.allocate_buffer(input_size)
    offset = 0
    for arg in node.args:
        arg_typ = arg._metadata["type"]

        if arg_typ._is_prim_word:
            # Single 32-byte value
            arg_val = Expr(arg, ctx).lower_value()
            b.mstore(b.add(input_buf._ptr, IRLiteral(offset)), arg_val)
            offset += 32
        else:
            # Array (uint256[2]) - copy from memory
            # arg_val is a pointer to the array in memory
            arg_ptr = Expr(arg, ctx).lower().operand
            for i in range(arg_typ.count):
                word = b.mload(b.add(arg_ptr, IRLiteral(i * 32)))
                b.mstore(b.add(input_buf._ptr, IRLiteral(offset)), word)
                offset += 32

    # Output buffer (64 bytes for resulting point)
    output_buf = ctx.allocate_buffer(64)

    # Call precompile
    success = b.staticcall(
        b.gas(), IRLiteral(precompile), input_buf._ptr, IRLiteral(input_size), output_buf._ptr, IRLiteral(64)
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
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    block_num = Expr(node.args[0], ctx).lower_value()

    # Clamp block number to valid range:
    # block_num >= block.number - BLOCKHASH_LOOKBACK_LIMIT AND block_num < block.number
    current_block = b.number()
    lower_bound = b.sub(current_block, IRLiteral(BLOCKHASH_LOOKBACK_LIMIT))

    # Clamp: max(lower_bound, min(block_num, current_block - 1))
    # If block_num < lower_bound => use lower_bound (will return 0)
    # If block_num >= current_block => use current_block (will return 0)
    # The legacy code uses clamp("lt", clamp("sge", x, lower), "number")
    # which ensures block_num >= lower_bound AND block_num < current_block

    # First clamp: sge check (signed >= lower_bound)
    is_ge_lower = b.slt(block_num, lower_bound)
    clamped1 = b.select(is_ge_lower, lower_bound, block_num)

    # Second clamp: lt check (< current_block)
    is_ge_current = b.iszero(b.lt(clamped1, current_block))
    clamped2 = b.select(is_ge_current, current_block, clamped1)

    return b.blockhash(clamped2)


def lower_blobhash(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    blobhash(index) -> bytes32

    Returns versioned hash of blob at given index (Cancun+).
    """
    from vyper.codegen_venom.expr import Expr

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
    from vyper.builtins.functions import AsWeiValue
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    value = Expr(node.args[0], ctx).lower_value()
    typ = node.args[0]._metadata["type"]

    # Get the denomination multiplier from the legacy builtin
    denom = AsWeiValue().get_denomination(node)

    if denom == 1:
        # No multiplication needed for "wei"
        if isinstance(typ, DecimalT):
            # Decimal case: just divide by DECIMAL_DIVISOR
            return b.div(value, IRLiteral(DECIMAL_DIVISOR))
        else:
            return value

    if isinstance(typ, DecimalT):
        # Decimal: multiply first, then divide by DECIMAL_DIVISOR
        # This maintains precision: (value * denom) / DECIMAL_DIVISOR
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
# Integer Square Root
# =============================================================================


def lower_isqrt(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    isqrt(x) -> uint256

    Integer square root using Babylonian method.
    Returns floor(sqrt(x)).

    Port of legacy IRnode implementation line-by-line.
    """
    from vyper.codegen_venom.expr import Expr

    b = ctx.builder

    x = Expr(node.args[0], ctx).lower_value()

    # Create mutable variables y and z
    # Legacy: ["with", y, x, ["with", z, 181, ...]]
    y = b.new_variable()
    z = b.new_variable()
    b.assign_to(x, y)
    b.assign_to(IRLiteral(181), z)

    # Scale based on magnitude - series of conditional adjustments
    # These use "ge" comparisons and conditionally update y and z

    # if y >= 2^136: y >>= 128, z <<= 64
    cond1 = b.iszero(b.lt(y, IRLiteral(2 ** (128 + 8))))  # ge = not lt
    new_y1 = b.shr(IRLiteral(128), y)
    new_z1 = b.shl(IRLiteral(64), z)
    b.assign_to(b.select(cond1, new_y1, y), y)
    b.assign_to(b.select(cond1, new_z1, z), z)

    # if y >= 2^72: y >>= 64, z <<= 32
    cond2 = b.iszero(b.lt(y, IRLiteral(2 ** (64 + 8))))
    new_y2 = b.shr(IRLiteral(64), y)
    new_z2 = b.shl(IRLiteral(32), z)
    b.assign_to(b.select(cond2, new_y2, y), y)
    b.assign_to(b.select(cond2, new_z2, z), z)

    # if y >= 2^40: y >>= 32, z <<= 16
    cond3 = b.iszero(b.lt(y, IRLiteral(2 ** (32 + 8))))
    new_y3 = b.shr(IRLiteral(32), y)
    new_z3 = b.shl(IRLiteral(16), z)
    b.assign_to(b.select(cond3, new_y3, y), y)
    b.assign_to(b.select(cond3, new_z3, z), z)

    # if y >= 2^24: y >>= 16, z <<= 8
    cond4 = b.iszero(b.lt(y, IRLiteral(2 ** (16 + 8))))
    new_y4 = b.shr(IRLiteral(16), y)
    new_z4 = b.shl(IRLiteral(8), z)
    b.assign_to(b.select(cond4, new_y4, y), y)
    b.assign_to(b.select(cond4, new_z4, z), z)

    # z = z * (y + 2^16) / 2^18
    scaled_z = b.div(b.mul(z, b.add(y, IRLiteral(2**16))), IRLiteral(2**18))
    b.assign_to(scaled_z, z)

    # 7 iterations of Babylonian refinement: z = (z + x/z) / 2
    for _ in range(7):
        next_z = b.div(b.add(b.div(x, z), z), IRLiteral(2))
        b.assign_to(next_z, z)

    # Final check: if x/z < z, return x/z (handles oscillation at perfect squares)
    # Legacy: ["with", "t", ["div", x, z], ["select", ["lt", z, "t"], z, "t"]]
    t = b.div(x, z)
    return b.select(b.lt(z, t), z, t)


# =============================================================================
# Debug
# =============================================================================


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
    "isqrt": lower_isqrt,
    "breakpoint": lower_breakpoint,
}
