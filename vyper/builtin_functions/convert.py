import decimal
import functools
import math

from vyper import ast as vy_ast
from vyper.codegen.core import (
    LLLnode,
    bytes_clamp,
    bytes_data_ptr,
    clamp_basetype,
    get_bytearray_length,
    getpos,
    int_clamp,
    load_word,
    sar,
    shl,
    shr,
    unwrap_location,
)
from vyper.codegen.expr import Expr
from vyper.codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    StringType,
    is_base_type,
    is_bytes_m_type,
    is_decimal_type,
    is_integer_type,
)
from vyper.exceptions import CompilerPanic, InvalidLiteral, StructureException, TypeMismatch
from vyper.utils import DECIMAL_DIVISOR, SizeLimits, int_bounds


def _FAIL(ityp, otyp, pos=None):
    raise TypeMismatch(f"Can't convert {ityp} to {otyp}", pos)


# helper function for `_input_types`
# generates a string representation of a type
# (makes up for lack of proper hierarchy in LLL type system)
# (ideally would use type generated during annotation, but
# not available for builtins)
def _type_class_of(typ):
    if is_integer_type(typ):
        return "int"
    if is_bytes_m_type(typ):
        return "bytes_m"
    if is_decimal_type(typ):
        return "decimal"
    if isinstance(typ, BaseType):
        return typ.typ  # e.g., "bool"
    if isinstance(typ, ByteArrayType):
        return "bytes"
    if isinstance(typ, StringType):
        return "string"


def _input_types(*allowed_types):
    def decorator(f):
        @functools.wraps(f)
        def check_input_type(expr, arg, out_typ):
            # convert arg to out_typ.
            # (expr is the AST corresponding to `arg`)
            ityp = _type_class_of(arg.typ)
            ok = ityp in allowed_types
            # user safety: disallow convert from type to itself
            ok &= arg.typ != out_typ
            if not ok:
                _FAIL(arg.typ, out_typ, expr)
            return f(expr, arg, out_typ)

        return check_input_type

    return decorator


def _bytes_to_num(arg, out_typ, signed):
    # converting a bytestring to a number:
    # bytestring and bytes_m are right-padded with zeroes, int is left-padded.
    # convert by shr or sar the number of zero bytes (converted to bits)
    # e.g. "abcd000000000000" -> bitcast(000000000000abcd, output_type)

    if isinstance(arg.typ, ByteArrayLike):
        _len = get_bytearray_length(arg)
        arg = load_word(bytes_data_ptr(arg))
        num_zero_bits = ["mul", 8, ["sub", 32, _len]]
    elif is_bytes_m_type(arg.typ):
        info = arg.typ._bytes_info
        num_zero_bits = 8 * (32 - info.m)
    else:
        raise CompilerPanic("unreachable")  # pragma: notest

    if signed:
        ret = sar(num_zero_bits, arg)
    else:
        ret = shr(num_zero_bits, arg)

    annotation = (f"__intrinsic__byte_array_to_num({out_typ})",)
    return LLLnode.from_list(ret, annotation=annotation)


# truncate from fixed point decimal to int
def _fixed_to_int(x, out_typ, decimals=10):
    return LLLnode.from_list(["sdiv", x, 10 ** decimals], typ=out_typ)


# promote from int to fixed point decimal
def _int_to_fixed(x, out_typ, decimals=10):
    return LLLnode.from_list(["mul", x, 10 ** decimals], typ=out_typ)


def _check_bytes(expr, arg, output_type, max_bytes_allowed):
    if isinstance(arg.typ, ByteArrayLike):
        if arg.typ.maxlen > max_bytes_allowed:
            _FAIL(arg.typ, output_type, expr)
    else:
        # sanity check. should not have conversions to non-base types
        assert output_type.memory_bytes_required == 32


def _literal_int(expr, out_typ):
    # TODO: possible to reuse machinery from expr.py?
    int_info = out_typ._int_info
    if isinstance(expr, vy_ast.Hex):
        val = int(expr.value, 16)
    elif isinstance(expr, vy_ast.Bytes):
        val = int.from_bytes(expr.value, "big")
    else:
        # Int, Decimal
        val = int(expr.value)
    (lo, hi) = int_bounds(int_info.is_signed, int_info.bits)
    if not (lo <= val <= hi):
        raise InvalidLiteral("Number out of range", expr)
    return LLLnode.from_list(val, typ=out_typ)


def _literal_decimal(expr, out_typ):
    # TODO: possible to reuse machinery from expr.py?
    if isinstance(expr, vy_ast.Hex):
        val = decimal.Decimal(int(expr.value, 16))
    else:
        val = decimal.Decimal(expr.value)  # should work for Int, Decimal

    val = val * DECIMAL_DIVISOR

    (lo, hi) = (SizeLimits.MINDECIMAL, SizeLimits.MAXDECIMAL)
    if not (lo <= val <= hi):
        raise InvalidLiteral("Number out of range", expr)

    # sanity check type checker did its job
    assert math.ceil(val) == math.floor(val)

    return LLLnode.from_list(int(val), typ=out_typ)


# any base type or bytes/string
@_input_types("int", "decimal", "bytes_m", "address", "bool", "bytes", "string")
def to_bool(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, 32)  # should we restrict to Bytes[1]?

    if isinstance(arg.typ, ByteArrayType):
        # no clamp. checks for any nonzero bytes.
        arg = _bytes_to_num(arg, out_typ, signed=False)

    # NOTE: for decimal, the behavior is x != 0.0,
    # (we do not issue an `sdiv DECIMAL_DIVISOR`)

    return LLLnode.from_list(["iszero", ["iszero", arg]], typ=out_typ)


# special clamp for uint/sint conversions
# uint -> sint requires input < sint::max_value
# sint -> uint requires input >= 0
# these are both equivalent to checking that the top bit is set
# (e.g. for uint8 that the 8th bit is set, same for int8)
def _signedness_clamp(arg, bits):
    return int_clamp(arg, bits=bits - 1, signed=False)


# clamp for dealing with conversions between numeric types (from arg to dst)
def _num_clamp(arg, dst_info, arg_info):
    if dst_info.is_signed != arg_info.is_signed:
        arg = _signedness_clamp(arg, arg_info.bits)

    # if, not elif (could be two clamps!)
    # TODO is it possible to make this more efficient?
    if dst_info.bits < arg_info.bits:
        arg = int_clamp(arg, dst_info.bits, dst_info.is_signed)

    return arg


@_input_types("int", "bytes_m", "decimal", "bytes", "address", "bool")
def to_int(expr, arg, out_typ):

    int_info = out_typ._int_info

    assert int_info.bits % 8 == 0
    _check_bytes(expr, arg, out_typ, 32)

    if isinstance(expr, vy_ast.Constant):
        return _literal_int(expr, out_typ)

    elif isinstance(arg.typ, ByteArrayType):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=int_info.is_signed)
        if arg_typ.maxlen * 8 > int_info.bits:
            arg = int_clamp(arg, int_info.bits, signed=int_info.is_signed)

    elif is_bytes_m_type(arg.typ):
        arg_info = arg.typ._bytes_info
        arg = _bytes_to_num(arg, out_typ, signed=int_info.is_signed)
        if arg_info.m_bits > int_info.bits:
            arg = int_clamp(arg, int_info.bits, signed=int_info.is_signed)

    elif is_decimal_type(arg.typ):
        arg_info = arg.typ._decimal_info
        arg = _fixed_to_int(arg, out_typ, decimals=arg_info.decimals)
        arg = _num_clamp(arg, int_info, arg_info)

    elif is_integer_type(arg.typ):
        arg_info = arg.typ._int_info
        arg = _num_clamp(arg, int_info, arg_info)

    elif is_base_type(arg.typ, "address"):
        if int_info.is_signed:
            # TODO if possible, refactor to move this validation close to the entry of the function
            _FAIL(arg.typ, out_typ, expr)
        if int_info.bits > 160:
            arg = int_clamp(arg, 160, signed=False)

    return LLLnode.from_list(arg, typ=out_typ)


@_input_types("int", "bool", "bytes_m", "bytes")
def to_decimal(expr, arg, out_typ):
    # question: is converting from Bytes to decimal allowed?
    _check_bytes(expr, arg, out_typ, max_bytes_allowed=16)

    if isinstance(expr, vy_ast.Constant):
        return _literal_decimal(expr, out_typ)

    if isinstance(arg.typ, ByteArrayType):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=True)
        # TODO revisit this condition once we have more decimal types
        # and decimal bounds expand
        # will be something like: if info.m_bits > 168
        if arg_typ.maxlen * 8 > 128:
            arg = LLLnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)
        return LLLnode.from_list(arg, typ=out_typ)

    elif is_bytes_m_type(arg.typ):
        info = arg.typ._bytes_info
        arg = _bytes_to_num(arg, out_typ, signed=True)
        # TODO revisit this condition once we have more decimal types
        # and decimal bounds expand
        # will be something like: if info.m_bits > 168
        if info.m_bits > 128:
            arg = LLLnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)

        return LLLnode.from_list(arg, typ=out_typ)

    # for the clamp, pretend it's int128 because int128 clamps are cheaper
    # (and then multiply into the decimal base afterwards)
    elif is_integer_type(arg.typ):
        int_info = arg.typ._int_info
        # TODO revisit this condition once we have more decimal types
        # and decimal bounds expand. (note that right now decimal bounds
        # are -2**127 and 2**127 - 1).
        # will be something like: if info.m_bits > 168
        # TODO this should probably use _num_clamp instead
        if int_info.bits > 128:
            arg = int_clamp(arg, 128, signed=True)

    elif is_base_type(arg.typ, "bool"):
        pass
    else:
        raise CompilerPanic("unreachable")  # pragma: notest

    return _int_to_fixed(arg, out_typ)


@_input_types("int", "decimal", "bytes_m", "address", "bytes", "bool")
def to_bytes_m(expr, arg, out_typ):
    out_info = out_typ._bytes_info
    _check_bytes(expr, arg, out_typ, max_bytes_allowed=out_info.m)

    if isinstance(arg.typ, ByteArrayType):
        bytes_val = load_word(bytes_data_ptr(arg))

        # zero out any dirty bytes (which can happen in the last
        # word of a bytearray)
        len_ = get_bytearray_length(arg)
        num_zero_bits = LLLnode.from_list(["mul", ["sub", 32, len_], 8])
        with num_zero_bits.cache_when_complex("bits") as (b, num_zero_bits):
            arg = shl(num_zero_bits, shr(num_zero_bits, bytes_val))
            arg = b.resolve(arg)

    elif is_integer_type(arg.typ) or is_base_type(arg.typ, "address"):
        int_bits = arg.typ._int_info.bits

        if out_info.m_bits < int_bits:
            # question: allow with runtime clamp?
            # arg = int_clamp(m_bits, signed=int_info.signed)
            _FAIL(arg.typ, out_typ, expr)

        arg = shl(256 - out_info.m_bits, arg)

    elif is_bytes_m_type(arg.typ):
        arg_info = arg.typ._bytes_info
        # clamp if it's a downcast
        if arg_info.m > out_info.m:
            arg = bytes_clamp(arg, out_info.m)

    else:
        # bool, decimal
        arg = shl(256 - out_info.m_bits, arg)  # question: is this right?

    return LLLnode.from_list(arg, typ=out_typ)


@_input_types("bytes_m", "int", "bytes")
def to_address(expr, arg, out_typ):
    # question: should this be allowed?
    if is_integer_type(arg.typ):
        if arg.typ._int_info.is_signed:
            _FAIL(arg.typ, out_typ, expr)

    # TODO once we introduce uint160, we can just check that arg
    # is unsigned, and then call to_int(expr, arg, uint160) because
    # the logic is equivalent.

    # disallow casting from Bytes[N>20]
    _check_bytes(expr, arg, out_typ, 32)

    if isinstance(arg.typ, ByteArrayType):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=False)
        # clamp after shift
        if arg_typ.maxlen > 20:
            arg = int_clamp(arg, 160, signed=False)

    if is_bytes_m_type(arg.typ):
        info = arg.typ._bytes_info
        arg = _bytes_to_num(arg, out_typ, signed=False)

        # clamp after shift
        if info.m > 20:
            arg = int_clamp(arg, 160, signed=False)

    elif is_integer_type(arg.typ):
        arg_info = arg.typ._int_info
        if arg_info.bits > 160 or arg_info.is_signed:
            arg = int_clamp(arg, 160, signed=False)

    return LLLnode.from_list(arg, typ=out_typ)


# question: should we allow bytesM -> String?
@_input_types("bytes")
def to_string(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # NOTE: this is a pointer cast
    return LLLnode.from_list(arg, typ=out_typ)


@_input_types("string")
def to_bytes(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # TODO: more casts

    # NOTE: this is a pointer cast
    return LLLnode.from_list(arg, typ=out_typ)


def convert(expr, context):
    if len(expr.args) != 2:
        raise StructureException("The convert function expects two parameters.", expr)

    arg_ast = expr.args[0]
    arg = Expr(arg_ast, context).lll_node
    out_typ = context.parse_type(expr.args[1])

    if isinstance(arg.typ, BaseType):
        arg = unwrap_location(arg)
    with arg.cache_when_complex("arg") as (b, arg):
        if is_base_type(out_typ, "bool"):
            ret = to_bool(arg_ast, arg, out_typ)
        elif is_base_type(out_typ, "address"):
            ret = to_address(arg_ast, arg, out_typ)
        elif is_integer_type(out_typ):
            ret = to_int(arg_ast, arg, out_typ)
        elif is_bytes_m_type(out_typ):
            ret = to_bytes_m(arg_ast, arg, out_typ)
        elif is_decimal_type(out_typ):
            ret = to_decimal(arg_ast, arg, out_typ)
        elif isinstance(out_typ, ByteArrayType):
            ret = to_bytes(arg_ast, arg, out_typ)
        elif isinstance(out_typ, StringType):
            ret = to_string(arg_ast, arg, out_typ)
        else:
            raise StructureException(f"Conversion to {out_typ} is invalid.", arg_ast)

        ret = b.resolve(ret)

    return LLLnode.from_list(ret, pos=getpos(expr))
