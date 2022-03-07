import math
import warnings
from decimal import Decimal

from vyper import ast as vy_ast
from vyper.builtin_functions.signatures import signature
from vyper.codegen.core import (
    LLLnode,
    add_ofst,
    clamp_basetype,
    get_bytearray_length,
    getpos,
    int_clamp,
    load_op,
    shl,
    shr,
    wordsize,
)
from vyper.codegen.types import (
    DYNAMIC_ARRAY_OVERHEAD,
    BaseType,
    ByteArrayType,
    StringType,
    get_type,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch
from vyper.utils import DECIMAL_DIVISOR, MemoryPositions, SizeLimits


def _byte_array_to_num(arg, out_type, clamp):
    """
    Generate LLL which takes a <32 byte array as input and returns a number
    """

    with arg.cache_when_complex("bs_start") as (b1, bs_start):

        len_ = get_bytearray_length(bs_start)
        val = unwrap_location(get_bytearray_ptr(bs_start))

        with len_.cache_when_complex("len_") as (b2, len_), val.cache_when_complex("val") as (
            b3,
            val,
        ):

            # converting a bytestring to a number:
            # bytestring is right-padded with zeroes, int is left-padded.
            # convert by shr the number of zero bytes (converted to bits)
            # e.g. "abcd000000000000" -> bitcast(000000000000abcd, output_type)
            num_zero_bits = ["mul", 8, ["sub", 32, len_]]
            result = LLLnode.from_list(shr(num_zero_bits, val), typ=out_type)

            if clamp:
                result = clamp_basetype(result)

            return LLLnode.from_list(
                b1.resolve(b2.resolve(b3.resolve(result))),
                typ=BaseType(out_type),
                annotation=f"__intrinsic__byte_array_to_num({out_type})",
            )


def _check_bytes(expr, arg, output_type, max_input_bytes=32):
    if isinstance(arg.typ, ByteArrayLike):
        if arg.typ.maxlen > max_input_bytes:
            raise TypeMismatch(
                f"Cannot convert {arg.typ} to {output_type}",
                expr,
            )
    else:
        # sanity check. should not have conversions to non-base types
        assert output_type.memory_bytes_required == 32


def _fixed_to_int(x, decimals=10):
    return ["sdiv", x, 10 ** decimals]


def _int_to_fixed(x, decimals=10):
    return ["mul", x, 10 ** decimals]


@input_types(BASE_TYPES)
def to_bool(expr, arg, out_typ):
    otyp = BaseType("bool")
    _check_bytes(expr, arg, otyp)

    if isinstance(arg.typ, ByteArrayType):
        arg = byte_array_to_num(arg, "uint256")

    # NOTE: for decimal, the behavior is x != 0.0,
    # not `x >= 1.0 and x <= -1.0` since
    # we do not issue an (sdiv DECIMAL_DIVISOR)

    return LLLnode.from_list(["iszero", ["iszero", arg]], typ=otyp, pos=getpos(expr))


def _literal_int(expr, out_typ):
    val = int(expr.value)  # should work for Int, Decimal, Hex
    (lo, hi) = int_bounds(int_info.is_signed, int_info.bits)
    if not (lo <= val <= hi):
        raise InvalidLiteral(f"Number out of range", expr)
    return LLLnode.from_list(arg, typ=out_typ, is_literal=True, pos=getpos(expr))


# to generalized integer
@input_types(FIXED_POINT_TYPES, INTEGER_TYPES, BYTES_M_TYPES, ByteArrayType)
def _to_int(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ)

    int_info = parse_integer_typeinfo(arg.typ.typ)

    if isinstance(expr, vy_ast.Constant):
        return _literal_int(expr, out_typ)

    if isinstance(arg.typ, BytesLike):
        # decide whether to do runtime clamp or not
        if arg.typ.maxlen * 8 > int_info.bits:
            raise TypeMismatch(f"Cannot cast {arg.typ} to {out_typ}", expr)
        arg = byte_array_to_num(arg, out_typ, clamp=False)

    if is_base_type(arg.typ, "decimal"):
        # TODO: clamps
        return LLLnode.from_list(["sdiv", in_arg, DECIMAL_DIVISOR], typ=out_typ)

    if isinstance(arg.typ, BYTES_M_TYPES):
        # TODO: clamps
        pass

    if isinstance(arg.typ, INTEGER_TYPES):
        ret = ["seq"]
        arg_info = parse_integer_typeinfo(arg.typ.typ)

        # generate clamps
        # special clamp for int/sint conversions
        if int_info.is_signed != arg_info.is_signed:
            # convert between signed and unsigned
            # e.g. uint256 -> int128, or int256 -> uint8
            # double check this works for both ways??
            ret.append(["assert", ["iszero", shr(int_info.bits, arg)]])
        elif arg_info.bits > int_info.bits:
            # cast to out_type so clamp_basetype works
            arg = LLLnode.from_list(arg, typ=out_typ)
            ret.append(clamp_basetype(arg))
        else:
            ret.append(arg)

        return LLLnode.from_list(ret, typ=out_typ, pos=getpos(expr))


# @signature(("bool", "int128", "int256", "uint8", "uint256", "bytes32", "Bytes", "address"), "*")
def to_decimal(expr, arg, _out_typ):
    if isinstance(expr, vy_ast.Constant):
        val = Decimal(expr.value)  # should work for Int, Decimal, Hex
        (lo, hi) = (MIN_DECIMAL, MAX_DECIMAL)
        if not (lo <= self.expr.val <= hi):
            raise InvalidLiteral(f"Number out of range", expr)

        return LLLnode.from_list(
            val * DECIMAL_DIVISOR,
            typ=BaseType(out_typ, is_literal=True),
            pos=getpos(self.expr),
        )

    # for the clamp, pretend it's int128 because int128 clamps are cheaper

    if isinstance(arg, BytesLike):
        # TODO only clamp if input > 16 bytes?
        arg = byte_array_to_num(arg, "int128", clamp=True)

    if isinstance(arg.typ, INTEGER_TYPES):
        int_info = parse_integer_typeinfo(arg.typ.typ)
        if int_info.bits > 128:
            arg = int_clamp(arg, 128, is_signed=True)

    # TODO bytesM? bool?

    return LLLnode.from_list(["mul", DECIMAL_DIVISOR, arg], typ=out_typ, pos=getpos(expr))


@signature(("int128", "int256", "uint8", "uint256", "address", "Bytes", "bool", "decimal"), "*")
def to_bytes32(expr, arg, _out_typ):
    in_arg = args[0]
    input_type, _len = get_type(in_arg)

    if input_type == "Bytes":
        if _len > 32:
            raise TypeMismatch(
                f"Unable to convert bytes[{_len}] to bytes32, max length is too " "large."
            )

        with in_arg.cache_when_complex("bytes") as (b1, in_arg):
            op = load_op(in_arg.location)
            ofst = wordsize(in_arg.location) * DYNAMIC_ARRAY_OVERHEAD
            bytes_val = [load_op(in_arg.location), get_bytearray_ptr(in_arg)]

            # zero out any dirty bytes (which can happen in the last
            # word of a bytearray)
            len_ = get_bytearray_length(in_arg)
            num_zero_bits = LLLnode.from_list(["mul", ["sub", 32, len_], 8])
            with num_zero_bits.cache_when_complex("bits") as (b2, num_zero_bits):
                ret = shl(num_zero_bits, shr(num_zero_bits, bytes_val))
                ret = b1.resolve(b2.resolve(ret))

    else:
        # literal
        ret = in_arg

    return LLLnode.from_list(ret, typ="bytes32", pos=getpos(expr))


@inputs(BYTES_M_TYPES, UINT_TYPES)
def to_address(expr, arg, out_typ):
    should_clamp = True
    if isinstance(arg.typ, BytesLike):
        # disallow casting from Bytes[N>20]
        if arg.typ.maxlen * 8 > 160:
            raise TypeMismatch(f"Cannot cast {arg.typ} to {out_typ}", expr)
        arg = byte_array_to_num(arg, out_typ, clamp=False)
        should_clamp = False

    if isinstance(arg.typ, INTEGER_TYPES):
        should_clamp = typeinfo.bits > 160 or typeinfo.is_signed

    if should_clamp:
        # cast to output type so clamp_basetype works
        arg = LLLnode.from_list(arg, typ=out_typ)
        return LLLnode.from_list(clamp_basetype(arg), typ=out_typ, pos=getpos(expr))
    return LLLnode.from_list(arg, typ=out_typ, pos=getpos(expr))


def _to_bytelike(expr, arg, out_typ):
    if bytetype == "String":
        otyp = StringType(arg.typ.maxlen)
    elif bytetype == "Bytes":
        otyp = ByteArrayType(arg.typ.maxlen)
    else:
        raise TypeMismatch(f"Invalid {bytetype} supplied")

    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # NOTE: this is a pointer cast
    return LLLnode(
        value=arg.value,
        args=arg.args,
        typ=out_typ,
        pos=getpos(expr),
        location=arg.location,
    )


def to_string(expr, arg, out_typ):
    return _to_bytelike(expr, args, out_typ)


def to_bytes(expr, arg, out_typ):
    return _to_bytelike(expr, arg, out_typ)


def convert(expr, context):
    if len(expr.args) != 2:
        raise StructureException("The convert function expects two parameters.", expr)

    arg = Expr(expr.args[0], context).lll_node
    out_typ = context.parse_type(expr.args[1])

    if output_type in CONVERSION_TABLE:
        return CONVERSION_TABLE[output_type](expr, arg, out_typ)
    else:
        raise StructureException(f"Conversion to {output_type} is invalid.", expr)


CONVERSION_TABLE = {
    "bool": to_bool,
    "address": (to_address, (BYTES_M_TYPES, UINT_TYPES)),
    "String": to_string,
    "Bytes": to_bytes,
}
for t in UNSIGNED_INTEER_TYPES:
    CONVERSION_TABLE[t] = to_uint
for t in SIGNED_INTEGER_TYPES:
    CONVERSION_TABLE[t] = to_sint
for t in FIXED_POINT_TYPES:
    CONVERSION_TABLE[t] = to_fixed
for t in BYTES_M_TYPES:
    CONVERSION_TABLE[t] = to_bytes_m
