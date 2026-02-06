"""
Type conversion built-in function.

convert(value, type) handles all type conversions in Vyper:
- to_bool: Any type -> bool
- to_int: Various types -> integer types
- to_decimal: Integer/bytes -> decimal
- to_bytes_m: Integer/bytes -> bytesN
- to_address: Integer/bytes -> address
- to_bytes/to_string: Bytestring casts
- to_flag: Integer -> Flag type
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, InvalidLiteral, TypeMismatch
from vyper.semantics.types import AddressT, BoolT, BytesM_T, BytesT, DecimalT, IntegerT, StringT
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.shortcuts import UINT160_T, UINT256_T
from vyper.semantics.types.user import FlagT
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def lower_convert(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    convert(value, type) - type conversion.

    Dispatches to type-specific conversion based on output type.
    """
    from vyper.codegen_venom.expr import Expr

    arg_node = node.args[0]
    in_t = arg_node._metadata["type"]
    out_t = node.args[1]._metadata["type"].typedef

    # For bytestrings we need pointer, for primitives we need value
    if isinstance(in_t, _BytestringT):
        arg_vv = Expr(arg_node, ctx).lower()
        arg = ctx.unwrap(arg_vv)  # Copies storage/transient to memory
    else:
        arg = Expr(arg_node, ctx).lower_value()

    # Dispatch based on output type
    if out_t == BoolT():
        return _to_bool(arg, in_t, out_t, arg_node, ctx)
    elif out_t == AddressT():
        return _to_address(arg, in_t, arg_node, ctx)
    elif isinstance(out_t, IntegerT):
        return _to_int(arg, in_t, out_t, arg_node, ctx)
    elif isinstance(out_t, DecimalT):
        return _to_decimal(arg, in_t, out_t, arg_node, ctx)
    elif isinstance(out_t, BytesM_T):
        return _to_bytes_m(arg, in_t, out_t, arg_node, ctx)
    elif isinstance(out_t, BytesT):
        return _to_bytes(arg, in_t, out_t, arg_node, ctx)
    elif isinstance(out_t, StringT):
        return _to_string(arg, in_t, out_t, arg_node, ctx)
    elif isinstance(out_t, FlagT):
        return _to_flag(arg, in_t, out_t, ctx)
    else:
        raise CompilerPanic(f"Unsupported conversion target: {out_t}")


def _get_folded_value(node: vy_ast.VyperNode):
    """
    Get the compile-time constant value for a node if available.

    Returns the Python value (int, bool, etc.) if the node is a constant or
    has a folded value, otherwise returns None.
    """
    # Check if it's a literal or has a folded constant value
    if isinstance(node, vy_ast.Constant):
        return node.value
    if node.has_folded_value:
        folded = node.get_folded_value()
        if isinstance(folded, vy_ast.Constant):
            return folded.value
    return None


def _check_literal_int_bounds(arg_node: vy_ast.VyperNode, out_t: IntegerT) -> None:
    """
    Check if a compile-time constant integer fits in the output type bounds.

    Raises InvalidLiteral if the value is out of range.
    """
    val = _get_folded_value(arg_node)
    if val is None:
        return

    # Only check numeric values
    if not isinstance(val, (int, bool)):
        return

    lo, hi = out_t.int_bounds
    if not (lo <= val <= hi):
        raise InvalidLiteral("Number out of range", arg_node)


def _to_bool(
    val: IROperand, in_t, out_t, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert any type to bool.

    Any nonzero value is True. For bytestrings, loads the data and checks.
    """
    _check_bytes(in_t, out_t, 32, arg_node)

    b = ctx.builder

    if isinstance(in_t, _BytestringT):
        # Check if any byte is nonzero (matches legacy behavior)
        # Load the actual data, not just length
        length = b.mload(val)
        data_ptr = b.add(val, IRLiteral(32))
        data = b.mload(data_ptr)

        # Right-shift to extract actual value based on length
        # For bytes that are shorter than 32, we need to shift right to
        # remove the padding zeros and get the actual numeric value
        # num_zero_bits = (32 - length) * 8
        num_zero_bits = b.mul(b.sub(IRLiteral(32), length), IRLiteral(8))
        # Shift right to get the actual numeric value
        shifted = b.shr(num_zero_bits, data)

        # Return True if any byte is nonzero
        return b.iszero(b.iszero(shifted))

    # For numeric/address/bool/flag: iszero(iszero(x)) normalizes to 0 or 1
    return b.iszero(b.iszero(val))


def _to_address(
    val: IROperand, in_t, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to address (160-bit unsigned).

    From signed integers: disallowed (type checker handles this)
    From bytes: right-shift if needed, clamp to 160 bits
    """
    # Use _to_int to get uint160, which handles clamping
    result = _to_int(val, in_t, UINT160_T, arg_node, ctx)
    return result


def _to_int(
    val: IROperand, in_t, out_t: IntegerT, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to integer type with clamping.

    Handles conversions from:
    - bytesM: right-shift to extract value
    - bytes/string: right-shift, with bounds check
    - decimal: divide by DECIMAL_DIVISOR
    - address: treated as uint160
    - flag: treated as uint256
    - other integer: clamp to bounds
    """
    _check_bytes(in_t, out_t, 32, arg_node)
    # Check literal bounds at compile time
    _check_literal_int_bounds(arg_node, out_t)

    b = ctx.builder

    # From bytes/string: load data, shift right
    if isinstance(in_t, _BytestringT):
        # Length at val, data at val+32
        length = b.mload(val)
        data_ptr = b.add(val, IRLiteral(32))
        data = b.mload(data_ptr)
        # Right-shift to convert left-aligned bytes to right-aligned int
        # num_zero_bits = (32 - len) * 8
        num_zero_bits = b.mul(b.sub(IRLiteral(32), length), IRLiteral(8))
        if out_t.is_signed:
            val = b.sar(num_zero_bits, data)
        else:
            val = b.shr(num_zero_bits, data)
        # Clamp if bytes could exceed output range
        if in_t.maxlen * 8 > out_t.bits:
            val = _int_clamp(val, out_t, ctx)
        return val

    # From bytesM: right-shift by (32 - M) * 8 bits
    if isinstance(in_t, BytesM_T):
        shift_bits = (32 - in_t.m) * 8
        if out_t.is_signed:
            val = b.sar(IRLiteral(shift_bits), val)
        else:
            val = b.shr(IRLiteral(shift_bits), val)
        # Clamp if bytesM could exceed output range
        if in_t.m * 8 > out_t.bits:
            val = _int_clamp(val, out_t, ctx)
        return val

    # From decimal: divide by divisor
    if isinstance(in_t, DecimalT):
        divisor = in_t.divisor
        # Clamp first to avoid overflow in intermediate
        out_lo, out_hi = out_t.int_bounds
        in_lo, in_hi = in_t.int_bounds
        # Scale output bounds by divisor for clamping the decimal value
        scaled_lo = out_lo * divisor
        scaled_hi = out_hi * divisor
        val = _clamp_numeric_convert(
            val, (in_lo, in_hi), (scaled_lo, scaled_hi), in_t.is_signed, ctx
        )
        # Now divide
        val = b.sdiv(val, IRLiteral(divisor))
        return val

    # From flag: treat as uint256, use int-to-int rules
    if isinstance(in_t, FlagT):
        # Flags can only convert to uint256
        return _int_to_int(val, UINT256_T, out_t, ctx)

    # From address: treat as uint160
    if in_t == AddressT():
        # Can only go to unsigned types >= 160 bits
        if out_t.bits < 160:
            val = _int_clamp(val, out_t, ctx)
        return val

    # From integer: int-to-int conversion
    if isinstance(in_t, IntegerT):
        return _int_to_int(val, in_t, out_t, ctx)

    # From bool: already 0 or 1, fits in any integer
    return val


def _to_decimal(
    val: IROperand, in_t, out_t: DecimalT, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to decimal (fixed-point).

    From integer: multiply by DECIMAL_DIVISOR with overflow check.
    From bytes: shift and interpret as decimal.
    """
    _check_bytes(in_t, out_t, 32, arg_node)

    b = ctx.builder
    divisor = out_t.divisor

    # From bytes/string
    if isinstance(in_t, _BytestringT):
        length = b.mload(val)
        data_ptr = b.add(val, IRLiteral(32))
        data = b.mload(data_ptr)
        num_zero_bits = b.mul(b.sub(IRLiteral(32), length), IRLiteral(8))
        val = b.sar(num_zero_bits, data)
        # Clamp to decimal bounds if needed
        if in_t.maxlen * 8 > 168:  # decimal is 168 bits
            val = _clamp_basetype(val, out_t, ctx)
        return val

    # From bytesM
    if isinstance(in_t, BytesM_T):
        shift_bits = (32 - in_t.m) * 8
        val = b.sar(IRLiteral(shift_bits), val)
        if in_t.m * 8 > 168:
            val = _clamp_basetype(val, out_t, ctx)
        return val

    # From integer: multiply by divisor
    if isinstance(in_t, IntegerT):
        # Clamp input to valid range before scaling
        out_lo, out_hi = out_t.int_bounds
        # Scale bounds for pre-multiplication check
        pre_lo = out_lo // divisor
        pre_hi = out_hi // divisor
        in_lo, in_hi = in_t.int_bounds
        val = _clamp_numeric_convert(val, (in_lo, in_hi), (pre_lo, pre_hi), in_t.is_signed, ctx)
        # Multiply by divisor
        result = b.mul(val, IRLiteral(divisor))
        return result

    # From bool: 0 or 1 * divisor
    if isinstance(in_t, BoolT):
        return b.mul(val, IRLiteral(divisor))

    return val


def _to_bytes_m(
    val: IROperand, in_t, out_t: BytesM_T, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to fixed bytes (bytesM).

    Values are left-aligned in 32-byte word.
    """
    _check_bytes(in_t, out_t, out_t.m, arg_node)

    b = ctx.builder

    # From bytes/string: load data, mask/shift as needed
    if isinstance(in_t, _BytestringT):
        length = b.mload(val)
        data_ptr = b.add(val, IRLiteral(32))
        data = b.mload(data_ptr)
        # Zero out any dirty high bits based on actual length
        num_zero_bits = b.mul(b.sub(IRLiteral(32), length), IRLiteral(8))
        val = b.shl(num_zero_bits, b.shr(num_zero_bits, data))
        return val

    # From bytesM: clamp downcast or widen
    if isinstance(in_t, BytesM_T):
        if in_t.m > out_t.m:
            # Downcast: assert low bytes are zero (bytes_clamp pattern)
            # bytesM is left-aligned, so check that shl(out_t.m * 8, val) == 0
            # This ensures bits that would be truncated are all zero
            shift_bits = out_t.m * 8
            shifted = b.shl(IRLiteral(shift_bits), val)
            b.assert_(b.iszero(shifted))
            return val
        # Widening is no-op (already left-aligned)
        return val

    # From integer/address/decimal: left-shift to align
    shift_bits = (32 - out_t.m) * 8
    return b.shl(IRLiteral(shift_bits), val)


def _to_bytes(
    val: IROperand, in_t, out_t: BytesT, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to dynamic bytes.

    From string: just reinterpret (check length)
    """
    # Only bytestring types can be converted to Bytes
    if not isinstance(in_t, _BytestringT):
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    # Ban converting same type (e.g. Bytes[20] to Bytes[21] upcast is not a real conversion)
    if isinstance(in_t, BytesT) and in_t.maxlen <= out_t.maxlen:
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    # Can't downcast literals with known length (e.g. b"abc" to Bytes[2])
    # Use reduced() to handle constant variables like `BAR: constant(Bytes[5])`
    reduced = arg_node.reduced() if arg_node.has_folded_value else arg_node
    if isinstance(reduced, vy_ast.Constant) and in_t.maxlen > out_t.maxlen:
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    b = ctx.builder

    # Both string->bytes and bytes->bytes are pointer casts
    # Just check length bounds
    if out_t.maxlen < in_t.maxlen:
        # Downcast: check actual length <= max
        length = b.mload(val)
        oob = b.gt(length, IRLiteral(out_t.maxlen))
        b.assert_(b.iszero(oob))

    # Return same pointer (reinterpreted)
    return val


def _to_string(
    val: IROperand, in_t, out_t: StringT, arg_node: vy_ast.VyperNode, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert to string.

    From bytes: just reinterpret (check length)
    """
    # Only bytestring types can be converted to String
    if not isinstance(in_t, _BytestringT):
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    # Ban converting same type (e.g. String[20] to String[21] upcast is not a real conversion)
    if isinstance(in_t, StringT) and in_t.maxlen <= out_t.maxlen:
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    # Can't downcast literals with known length (e.g. "abc" to String[2])
    # Use reduced() to handle constant variables like `BAR: constant(String[5])`
    reduced = arg_node.reduced() if arg_node.has_folded_value else arg_node
    if isinstance(reduced, vy_ast.Constant) and in_t.maxlen > out_t.maxlen:
        raise TypeMismatch(f"Can't convert {in_t} to {out_t}", arg_node)

    b = ctx.builder

    # bytes->string and string->string are pointer casts
    if out_t.maxlen < in_t.maxlen:
        # Downcast: check actual length <= max
        length = b.mload(val)
        oob = b.gt(length, IRLiteral(out_t.maxlen))
        b.assert_(b.iszero(oob))

    return val


def _to_flag(val: IROperand, in_t, out_t: FlagT, ctx: VenomCodegenContext) -> IROperand:
    """
    Convert integer to flag type.

    Only uint256 -> flag is allowed. Clamps to valid flag range.
    """
    b = ctx.builder

    n_members = len(out_t._flag_members)
    if n_members < 256:
        # Clamp: value must be < 2^n_members
        max_val = (1 << n_members) - 1
        oob = b.gt(val, IRLiteral(max_val))
        b.assert_(b.iszero(oob))

    return val


# === Helper functions ===


def _check_bytes(in_t, out_t, max_bytes_allowed: int, source_expr: vy_ast.VyperNode):
    """
    Validate bytestring input doesn't exceed maximum allowed size.

    Raises TypeMismatch if in_t is a bytestring with maxlen > max_bytes_allowed.
    """
    if isinstance(in_t, _BytestringT):
        if in_t.maxlen > max_bytes_allowed:
            raise TypeMismatch(f"Can't convert {in_t} to {out_t}", source_expr)


def _int_clamp(val: IROperand, out_t: IntegerT, ctx: VenomCodegenContext) -> IROperand:
    """Clamp value to integer type bounds."""
    b = ctx.builder
    lo, hi = out_t.int_bounds

    if out_t.is_signed:
        # sge(val, lo) = iszero(slt(val, lo))
        ge_lo = b.iszero(b.slt(val, IRLiteral(lo)))
        le_hi = b.iszero(b.sgt(val, IRLiteral(hi)))
        ok = b.and_(ge_lo, le_hi)
    else:
        # Unsigned: just check upper bound
        ok = b.iszero(b.gt(val, IRLiteral(hi)))

    b.assert_(ok)
    return val


def _clamp_basetype(val: IROperand, typ, ctx: VenomCodegenContext) -> IROperand:
    """Clamp value to type bounds (for DecimalT)."""
    b = ctx.builder
    lo, hi = typ.int_bounds

    if typ.is_signed:
        ge_lo = b.iszero(b.slt(val, IRLiteral(lo)))
        le_hi = b.iszero(b.sgt(val, IRLiteral(hi)))
        ok = b.and_(ge_lo, le_hi)
    else:
        ok = b.iszero(b.gt(val, IRLiteral(hi)))

    b.assert_(ok)
    return val


def _clamp_numeric_convert(
    val: IROperand,
    arg_bounds: tuple,
    out_bounds: tuple,
    arg_is_signed: bool,
    ctx: VenomCodegenContext,
) -> IROperand:
    """
    Clamp numeric value during conversion.

    Checks value is within output bounds, asserting if not.
    """
    b = ctx.builder
    arg_lo, arg_hi = arg_bounds
    out_lo, out_hi = out_bounds

    if arg_lo < out_lo:
        assert arg_is_signed, "bad assumption in numeric convert"
        # sge(val, out_lo)
        ge_lo = b.iszero(b.slt(val, IRLiteral(out_lo)))
        b.assert_(ge_lo)

    if arg_hi > out_hi:
        if arg_is_signed:
            le_hi = b.iszero(b.sgt(val, IRLiteral(out_hi)))
        else:
            le_hi = b.iszero(b.gt(val, IRLiteral(out_hi)))
        b.assert_(le_hi)

    return val


def _int_to_int(
    val: IROperand, in_t: IntegerT, out_t: IntegerT, ctx: VenomCodegenContext
) -> IROperand:
    """
    Convert between integer types with appropriate clamping.

    Handles sign changes and bit width changes.
    """
    b = ctx.builder

    if in_t.is_signed and not out_t.is_signed:
        # Signed to unsigned: check val >= 0, then clamp upper if narrowing
        if out_t.bits < in_t.bits:
            # Narrowing: need full unsigned clamp
            hi = (1 << out_t.bits) - 1
            ok = b.iszero(b.gt(val, IRLiteral(hi)))
            ge_zero = b.iszero(b.slt(val, IRLiteral(0)))
            ok = b.and_(ok, ge_zero)
            b.assert_(ok)
        else:
            # Widening or same size: just check >= 0
            ge_zero = b.iszero(b.slt(val, IRLiteral(0)))
            b.assert_(ge_zero)

    elif not in_t.is_signed and out_t.is_signed:
        # Unsigned to signed: check fits in signed range
        hi = (1 << (out_t.bits - 1)) - 1  # max positive signed value
        ok = b.iszero(b.gt(val, IRLiteral(hi)))
        b.assert_(ok)

    elif out_t.bits < in_t.bits:
        # Narrowing, same signedness
        val = _int_clamp(val, out_t, ctx)

    # else: widening, same signedness - no clamping needed

    return val


# Export handler
HANDLERS = {"convert": lower_convert}
