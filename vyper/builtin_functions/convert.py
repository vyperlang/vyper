import math
import warnings
from decimal import Decimal
import functools

from vyper import ast as vy_ast
from vyper.codegen.expr import Expr
from vyper.codegen.core import (
    LLLnode,
    add_ofst,
    clamp_basetype,
    get_bytearray_length,
    bytes_data_ptr,
    getpos,
    int_clamp,
    load_op,
    shl,
    shr,
    wordsize,
)
from vyper.codegen.types import (
    DYNAMIC_ARRAY_OVERHEAD,
    is_integer_type,
    is_bytes_m_type,
    parse_bytes_m_info,
    is_decimal_type,
    parse_decimal_info,
    parse_integer_typeinfo,
    BaseType,
    ByteArrayType,
    ByteArrayLike,
    StringType,
    INTEGER_TYPES,
    BYTES_M_TYPES,
    is_base_type,
    DECIMAL_TYPES,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import InvalidLiteral, StructureException, TypeMismatch
from vyper.utils import DECIMAL_DIVISOR, MemoryPositions, SizeLimits
from vyper.semantics.types.abstract import NumericAbstractType, BytesAbstractType, BytesMAbstractType, UnsignedIntegerAbstractType
from vyper.semantics.types import AddressDefinition, BoolDefinition, BytesArrayDefinition, StringDefinition


def _FAIL(ityp, otyp, pos=None):
    raise TypeMismatch(f"Can't convert {ityp} to {otyp}", pos)


def _input_types(*allowed_types):
    def decorator(f):
        @functools.wraps(f)
        def g(expr, arg, out_typ):
            # use new types bc typechecking is easier
            ityp = expr.args[0]._metadata["type"]
            ok = any(isinstance(ityp, t) for t in allowed_types)
            if not ok:
                _FAIL(expr._metadata["type"], out_typ, expr)
            return f(expr, arg, out_typ)
        return g
    return decorator


def _byte_array_to_num(arg, out_type, clamp):
    """
    Generate LLL which takes a <32 byte array as input and returns a number
    """
    len_ = get_bytearray_length(arg)
    val = unwrap_location(bytes_data_ptr(arg))

    # converting a bytestring to a number:
    # bytestring is right-padded with zeroes, int is left-padded.
    # convert by shr the number of zero bytes (converted to bits)
    # e.g. "abcd000000000000" -> bitcast(000000000000abcd, output_type)
    num_zero_bits = ["mul", 8, ["sub", 32, len_]]
    result = LLLnode.from_list(shr(num_zero_bits, val), typ=out_type)

    if clamp:
        result = clamp_basetype(result)

    return LLLnode.from_list(
        result,
        typ=BaseType(out_type),
        annotation=f"__intrinsic__byte_array_to_num({out_type})",
    )


def _fixed_to_int(x, out_typ, decimals=10):
    return LLLnode.from_list(["sdiv", x, 10 ** decimals], typ=out_typ)


def _int_to_fixed(x, out_typ, decimals=10):
    return LLLnode.from_list(["mul", x, 10 ** decimals], typ=out_typ)


def _check_bytes(expr, arg, output_type, max_bytes_allowed):
    if isinstance(arg.typ, ByteArrayLike):
        if arg.typ.maxlen > max_bytes_allowed:
            raise TypeMismatch(
                f"Cannot convert {arg.typ} to {output_type}",
                expr,
            )
    else:
        # sanity check. should not have conversions to non-base types
        assert output_type.memory_bytes_required == 32


# any base type or bytes/string
@_input_types(NumericAbstractType, AddressDefinition, BoolDefinition, BytesAbstractType)
def to_bool(expr, arg, out_typ):
    otyp = BaseType("bool")
    _check_bytes(expr, arg, otyp, 32)  # should we restrict to Bytes[1]?

    if isinstance(arg.typ, ByteArrayType):
        arg = _byte_array_to_num(arg, "uint256")

    # NOTE: for decimal, the behavior is x != 0.0,
    # not `x >= 1.0 and x <= -1.0` since
    # we do not issue an (sdiv DECIMAL_DIVISOR)

    return LLLnode.from_list(["iszero", ["iszero", arg]], typ=otyp)


def _literal_int(expr, out_typ):
    val = int(expr.value)  # should work for Int, Decimal, Hex
    (lo, hi) = int_bounds(int_info.is_signed, int_info.bits)
    if not (lo <= val <= hi):
        raise InvalidLiteral(f"Number out of range", expr)
    return LLLnode.from_list(arg, typ=out_typ, is_literal=True)


@_input_types(NumericAbstractType, BytesAbstractType, BoolDefinition)
def to_int(expr, arg, out_typ):

    int_info = parse_integer_typeinfo(arg.typ.typ)

    assert int_info.bits % 8 == 0
    _check_bytes(expr, arg.typ, out_typ, int_info.bits // 8)

    if isinstance(expr, vy_ast.Constant):
        return _literal_int(expr, out_typ)

    if isinstance(arg.typ, ByteArrayLike):
        arg = _byte_array_to_num(arg, out_typ, clamp=False)

    if is_decimal_type(arg.typ):
        info = parse_decimal_typeinfo(arg.typ.typ)
        arg = _fixed_to_int(arg, out_typ, decimals=info.decimals)

    if is_bytes_m_type(arg.typ):
        m = parse_bytes_m_info(arg.typ.typ)
        m_bits = m * 8

        # NOTE bytesM to intN is like casting to bytesJ then intN
        # (where J = N/8)
        if m_bits < 256:  # TODO optimizer rule for this
            arg = shr(256 - m_bits, arg)
        is_downcast = m_bits > int_info.bits  # do we need to clamp?
        if is_downcast:
            arg = LLLnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)
        # TODO we need signextend for signed ints.

    if is_integer_type(arg.typ):
        arg_info = parse_integer_typeinfo(arg.typ.typ)

        # generate clamps
        # special clamp for uint/sint conversions
        # uint -> sint requires input < sint::max_value
        # sint -> uint requires input >= 0
        # it turns out that these are both equivalent to
        # checking that the top bit is set (e.g. for uint8
        # that the 8th bit is set)
        if int_info.is_signed != arg_info.is_signed:
            # convert between signed and unsigned
            # e.g. uint256 -> int128, or int256 -> uint8
            tmp = ["seq"]
            # NOTE: sar works for both ways, including uint256 <-> int256
            tmp.append(["assert", ["iszero", sar(int_info.bits, arg)]])
            tmp.append(arg)
            arg = b.resolve(tmp)

        elif arg_info.bits > int_info.bits:
            # cast to out_type so clamp_basetype works
            arg = LLLnode.from_list(arg, typ=out_typ)
        else:
            pass  # upcasting with no change in signedness; no clamp needed

    return LLLnode.from_list(arg, typ=out_typ)


@_input_types(NumericAbstractType, BoolDefinition)
def to_decimal(expr, arg, _out_typ):
    if isinstance(expr, vy_ast.Constant):
        val = Decimal(expr.value)  # should work for Int, Decimal, Hex
        (lo, hi) = (MIN_DECIMAL, MAX_DECIMAL)
        if not (lo <= self.expr.val <= hi):
            raise InvalidLiteral(f"Number out of range", expr)

        return LLLnode.from_list(
            val * DECIMAL_DIVISOR,
            typ=BaseType(out_typ, is_literal=True),
        )

    # for the clamp, pretend it's int128 because int128 clamps are cheaper
    # (and then multiply into the decimal base afterwards)
    if is_integer_type(arg.typ):
        int_info = parse_integer_typeinfo(arg.typ.typ)
        if int_info.bits > 128:
            arg = int_clamp(arg, 128, is_signed=True)

    return LLLnode.from_list(["mul", DECIMAL_DIVISOR, arg], typ=out_typ)


@_input_types(NumericAbstractType, AddressDefinition, BytesAbstractType, BoolDefinition)
def to_bytes_m(expr, arg, out_typ):
    m = parse_bytes_m_info(out_typ.typ)
    _check_bytes(expr, arg, out_typ, max_bytes_allowed=m)

    if isinstance(arg.typ, ByteArrayType):
        load = load_op(arg.location)
        bytes_val = [load, bytes_data_ptr(arg)]

        # zero out any dirty bytes (which can happen in the last
        # word of a bytearray)
        len_ = get_bytearray_length(arg)
        num_zero_bits = LLLnode.from_list(["mul", ["sub", 32, len_], 8])
        with num_zero_bits.cache_when_complex("bits") as (b2, num_zero_bits):
            ret = shl(num_zero_bits, shr(num_zero_bits, bytes_val))
            ret = b1.resolve(b2.resolve(ret))

    else:
        # TODO shl for int types.
        ret = arg

    return LLLnode.from_list(ret, typ=out_typ)


@_input_types(BytesAbstractType, UnsignedIntegerAbstractType)
def to_address(expr, arg, out_typ):
    should_clamp = True
    if isinstance(arg.typ, ByteArrayLike):
        # disallow casting from Bytes[N>20]
        if arg.typ.maxlen * 8 > 160:
            raise TypeMismatch(f"Cannot cast {arg.typ} to {out_typ}", expr)
        arg = _byte_array_to_num(arg, out_typ, clamp=False)
        should_clamp = False

    if is_bytes_m_type(arg.typ):
        m = parse_bytes_m_info(arg.typ.typ)
        m_bits = m * 8
        if m_bits < 256:
            arg = shr(256 - m_bits, arg)

        should_clamp = m_bits > 160

    if is_integer_type(arg.typ):
        int_info = parse_integer_typeinfo(arg.typ.typ)
        should_clamp = int_info.bits > 160 or int_info.is_signed

    if should_clamp:
        # NOTE: cast to output type so clamp_basetype works
        arg = clamp_basetype(LLLnode.from_list(arg, typ=out_typ))

    return LLLnode.from_list(arg, typ=out_typ)


# question: should we allow bytesM -> String?
@_input_types(BytesArrayDefinition)
def to_string(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # NOTE: this is a pointer cast
    return LLLnode.from_list(arg, typ=out_typ)


@_input_types(StringDefinition)
def to_bytes(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # TODO: more casts

    # NOTE: this is a pointer cast
    return LLLnode.from_list(arg, typ=out_typ)


def convert(expr, context):
    if len(expr.args) != 2:
        raise StructureException("The convert function expects two parameters.", expr)

    arg = Expr(expr.args[0], context).lll_node
    out_typ = context.parse_type(expr.args[1])

    with arg.cache_when_complex("arg") as (b, arg):
        if is_base_type(out_typ, "bool"):
            ret = to_bool(expr, arg, out_typ)
        elif is_base_type(out_typ, "address"):
            ret = to_address(expr, arg, out_typ)
        elif is_integer_type(out_typ):
            ret = to_int(expr, arg, out_typ)
        elif is_bytes_m_type(out_typ):
            ret = to_bytes_m(expr, arg, out_typ)
        elif is_decimal_type(out_typ):
            ret = to_decimal(expr, arg, out_typ)
        elif isinstance(out_typ, ByteArrayType):
            ret = to_bytes(expr, arg, out_typ)
        elif isinstance(out_typ, StringType):
            ret = to_string(expr, arg, out_typ)
        else:
            raise StructureException(f"Conversion to {output_type} is invalid.", expr)

        ret = b.resolve(ret)

    return LLLnode.from_list(ret, pos=getpos(expr))
