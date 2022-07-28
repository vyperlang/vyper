import decimal
import functools
import math

from vyper import ast as vy_ast
from vyper.codegen.core import (
    LOAD,
    IRnode,
    bytes_clamp,
    bytes_data_ptr,
    clamp,
    clamp_basetype,
    get_bytearray_length,
    int_clamp,
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
    EnumType,
    StringType,
    is_base_type,
    is_bytes_m_type,
    is_decimal_type,
    is_enum_type,
    is_integer_type,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidType,
    StructureException,
    TypeMismatch,
)
from vyper.utils import DECIMAL_DIVISOR, SizeLimits, round_towards_zero, unsigned_to_signed


def _FAIL(ityp, otyp, source_expr=None):
    # TODO consider changing this to InvalidType to be consistent
    # with the case when types are equal.
    raise TypeMismatch(f"Can't convert {ityp} to {otyp}", source_expr)


# helper function for `_input_types`
# generates a string representation of a type
# (makes up for lack of proper hierarchy in IR type system)
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
            if not ok:
                _FAIL(arg.typ, out_typ, expr)

            # user safety: disallow convert from type to itself
            # note allowance of [u]int256; this is due to type inference
            # on literals not quite working yet.
            if arg.typ == out_typ and not is_base_type(arg.typ, ("uint256", "int256")):
                raise InvalidType(f"value and target are both {out_typ}", expr)

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
        arg = LOAD(bytes_data_ptr(arg))
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
    return IRnode.from_list(ret, annotation=annotation)


def _clamp_numeric_convert(arg, arg_bounds, out_bounds, arg_is_signed):
    arg_lo, arg_hi = arg_bounds
    out_lo, out_hi = out_bounds

    if arg_lo < out_lo:
        # if not arg_is_signed, arg_lo is 0, so this branch cannot be hit
        assert arg_is_signed, "bad assumption in numeric convert"
        arg = clamp("sge", arg, out_lo)

    if arg_hi > out_hi:
        # out_hi must be smaller than MAX_UINT256, so clample makes sense.
        # add an assertion, just in case this assumption ever changes.
        assert out_hi < 2 ** 256 - 1, "bad assumption in numeric convert"
        CLAMP_OP = "sle" if arg_is_signed else "le"
        arg = clamp(CLAMP_OP, arg, out_hi)

    return arg


# truncate from fixed point decimal to int
def _fixed_to_int(arg, out_typ):
    arg_info = arg.typ._decimal_info
    out_info = out_typ._int_info

    DIVISOR = arg_info.divisor

    # block inputs which are out of bounds before truncation.
    # e.g., convert(255.1, uint8) should revert or fail to compile.
    out_lo, out_hi = out_info.bounds
    out_lo = out_lo * DIVISOR
    out_hi = out_hi * DIVISOR

    clamped_arg = _clamp_numeric_convert(arg, arg_info.bounds, (out_lo, out_hi), arg_info.is_signed)

    assert arg_info.is_signed, "should use unsigned div"  # stub in case we ever add ufixed
    return IRnode.from_list(["sdiv", clamped_arg, DIVISOR], typ=out_typ)


# promote from int to fixed point decimal
def _int_to_fixed(arg, out_typ):
    arg_info = arg.typ._int_info
    out_info = out_typ._decimal_info

    DIVISOR = out_info.divisor

    # block inputs which are out of bounds before promotion
    out_lo, out_hi = out_info.bounds
    out_lo = round_towards_zero(out_lo / decimal.Decimal(DIVISOR))
    out_hi = round_towards_zero(out_hi / decimal.Decimal(DIVISOR))

    clamped_arg = _clamp_numeric_convert(arg, arg_info.bounds, (out_lo, out_hi), arg_info.is_signed)

    return IRnode.from_list(["mul", clamped_arg, DIVISOR], typ=out_typ)


# clamp for dealing with conversions between int types (from arg to dst)
def _int_to_int(arg, out_typ):
    arg_info = arg.typ._int_info
    out_info = out_typ._int_info

    # do the same thing as
    # _clamp_numeric_convert(arg, arg_info.bounds, out_info.bounds, arg_info.is_signed)
    # but with better code size and gas.
    if arg_info.is_signed and not out_info.is_signed:

        # e.g. (clample (clampge arg 0) (2**128 - 1))

        # note that when out_info.bits == 256,
        # (clample arg 2**256 - 1) does not make sense.
        # see similar assertion in _clamp_numeric_convert.

        if out_info.bits < arg_info.bits:

            assert out_info.bits < 256, "unreachable"
            # note: because of the usage of signed=False, and the fact
            # that out_bits < 256 in this branch, below implies
            # not only (clample arg 2**128 - 1) but also (clampge arg 0).
            arg = int_clamp(arg, out_info.bits, signed=False)

        else:
            # note: this also works for out_bits == 256.
            arg = clamp("sge", arg, 0)

    elif not arg_info.is_signed and out_info.is_signed:
        # e.g. (uclample (uclampge arg 0) (2**127 - 1))
        # (note that (uclampge arg 0) always evaluates to true.)
        arg = int_clamp(arg, out_info.bits - 1, signed=False)

    elif out_info.bits < arg_info.bits:
        assert out_info.bits < 256, "unreachable"
        # narrowing conversion, signs are the same.
        # we can just use regular int clampers.
        arg = int_clamp(arg, out_info.bits, out_info.is_signed)

    else:
        # widening conversion, signs are the same.
        # we do not have to do any clamps.
        assert arg_info.is_signed == out_info.is_signed and out_info.bits >= arg_info.bits

    return IRnode.from_list(arg, typ=out_typ)


def _check_bytes(expr, arg, output_type, max_bytes_allowed):
    if isinstance(arg.typ, ByteArrayLike):
        if arg.typ.maxlen > max_bytes_allowed:
            _FAIL(arg.typ, output_type, expr)
    else:
        # sanity check. should not have conversions to non-base types
        assert output_type.memory_bytes_required == 32


# apply sign extension, if expected. note that the sign bit
# is always taken to be the first bit of the bytestring.
# (e.g. convert(0xff <bytes1>, int16) == -1)
def _signextend(expr, val, arg_typ):
    if isinstance(expr, vy_ast.Hex):
        assert len(expr.value[2:]) // 2 == arg_typ._bytes_info.m
        n_bits = arg_typ._bytes_info.m_bits
    else:
        assert len(expr.value) == arg_typ.maxlen
        n_bits = arg_typ.maxlen * 8

    return unsigned_to_signed(val, n_bits)


def _literal_int(expr, arg_typ, out_typ):
    # TODO: possible to reuse machinery from expr.py?
    int_info = out_typ._int_info
    if isinstance(expr, vy_ast.Hex):
        val = int(expr.value, 16)
    elif isinstance(expr, vy_ast.Bytes):
        val = int.from_bytes(expr.value, "big")
    elif isinstance(expr, (vy_ast.Int, vy_ast.Decimal, vy_ast.NameConstant)):
        val = expr.value
    else:  # pragma: no cover
        raise CompilerPanic("unreachable")

    if isinstance(expr, (vy_ast.Hex, vy_ast.Bytes)) and int_info.is_signed:
        val = _signextend(expr, val, arg_typ)

    (lo, hi) = int_info.bounds
    if not (lo <= val <= hi):
        raise InvalidLiteral("Number out of range", expr)

    # cast to int AFTER bounds check (ensures decimal is in bounds before truncation)
    val = int(val)

    return IRnode.from_list(val, typ=out_typ)


def _literal_decimal(expr, arg_typ, out_typ):
    if isinstance(expr, vy_ast.Hex):
        val = decimal.Decimal(int(expr.value, 16))
    else:
        val = decimal.Decimal(expr.value)  # should work for Int, Decimal
        val *= DECIMAL_DIVISOR

    # sanity check type checker did its job
    assert math.ceil(val) == math.floor(val)

    val = int(val)

    # apply sign extension, if expected
    out_info = out_typ._decimal_info
    if isinstance(expr, (vy_ast.Hex, vy_ast.Bytes)) and out_info.is_signed:
        val = _signextend(expr, val, arg_typ)

    if not SizeLimits.in_bounds("decimal", val):
        raise InvalidLiteral("Number out of range", expr)

    return IRnode.from_list(val, typ=out_typ)


# any base type or bytes/string
@_input_types("int", "decimal", "bytes_m", "address", "bool", "bytes", "string")
def to_bool(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, 32)  # should we restrict to Bytes[1]?

    if isinstance(arg.typ, ByteArrayType):
        # no clamp. checks for any nonzero bytes.
        arg = _bytes_to_num(arg, out_typ, signed=False)

    # NOTE: for decimal, the behavior is x != 0.0,
    # (we do not issue an `sdiv DECIMAL_DIVISOR`)

    return IRnode.from_list(["iszero", ["iszero", arg]], typ=out_typ)


@_input_types("int", "bytes_m", "decimal", "bytes", "address", "bool")
def to_int(expr, arg, out_typ):
    int_info = out_typ._int_info

    assert int_info.bits % 8 == 0
    _check_bytes(expr, arg, out_typ, 32)

    if isinstance(expr, vy_ast.Constant):
        return _literal_int(expr, arg.typ, out_typ)

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
        arg = _fixed_to_int(arg, out_typ)

    elif is_enum_type(arg.typ):
        if not is_base_type(out_typ, "uint256"):
            _FAIL(arg.typ, out_typ, expr)
        arg = _int_to_int(arg, out_typ)

    elif is_integer_type(arg.typ):
        arg = _int_to_int(arg, out_typ)

    elif is_base_type(arg.typ, "address"):
        if int_info.is_signed:
            # TODO if possible, refactor to move this validation close to the entry of the function
            _FAIL(arg.typ, out_typ, expr)
        if int_info.bits < 160:
            arg = int_clamp(arg, int_info.bits, signed=False)

    return IRnode.from_list(arg, typ=out_typ)


@_input_types("int", "bool", "bytes_m", "bytes")
def to_decimal(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, 32)

    out_info = out_typ._decimal_info

    if isinstance(expr, vy_ast.Constant):
        return _literal_decimal(expr, arg.typ, out_typ)

    if isinstance(arg.typ, ByteArrayType):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=True)
        if arg_typ.maxlen * 8 > 168:
            arg = IRnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)

        return IRnode.from_list(arg, typ=out_typ)

    elif is_bytes_m_type(arg.typ):
        info = arg.typ._bytes_info
        arg = _bytes_to_num(arg, out_typ, signed=True)
        if info.m_bits > 168:
            arg = IRnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)

        return IRnode.from_list(arg, typ=out_typ)

    elif is_integer_type(arg.typ):
        arg = _int_to_fixed(arg, out_typ)
        return IRnode.from_list(arg, typ=out_typ)

    elif is_base_type(arg.typ, "bool"):
        # TODO: consider adding _int_info to bool so we can use _int_to_fixed
        arg = ["mul", arg, 10 ** out_info.decimals]
        return IRnode.from_list(arg, typ=out_typ)
    else:
        raise CompilerPanic("unreachable")  # pragma: notest


@_input_types("int", "decimal", "bytes_m", "address", "bytes", "bool")
def to_bytes_m(expr, arg, out_typ):
    out_info = out_typ._bytes_info

    _check_bytes(expr, arg, out_typ, max_bytes_allowed=out_info.m)

    if isinstance(arg.typ, ByteArrayType):
        bytes_val = LOAD(bytes_data_ptr(arg))

        # zero out any dirty bytes (which can happen in the last
        # word of a bytearray)
        len_ = get_bytearray_length(arg)
        num_zero_bits = IRnode.from_list(["mul", ["sub", 32, len_], 8])
        with num_zero_bits.cache_when_complex("bits") as (b, num_zero_bits):
            arg = shl(num_zero_bits, shr(num_zero_bits, bytes_val))
            arg = b.resolve(arg)

    elif is_bytes_m_type(arg.typ):
        arg_info = arg.typ._bytes_info
        # clamp if it's a downcast
        if arg_info.m > out_info.m:
            arg = bytes_clamp(arg, out_info.m)

    elif is_integer_type(arg.typ) or is_base_type(arg.typ, "address"):
        int_bits = arg.typ._int_info.bits

        if out_info.m_bits < int_bits:
            # question: allow with runtime clamp?
            # arg = int_clamp(m_bits, signed=int_info.signed)
            _FAIL(arg.typ, out_typ, expr)

        # note: neg numbers not OOB. keep sign bit
        arg = shl(256 - out_info.m_bits, arg)

    elif is_decimal_type(arg.typ):
        if out_info.m_bits < arg.typ._decimal_info.bits:
            _FAIL(arg.typ, out_typ, expr)

        # note: neg numbers not OOB. keep sign bit
        arg = shl(256 - out_info.m_bits, arg)

    else:
        # bool
        arg = shl(256 - out_info.m_bits, arg)

    return IRnode.from_list(arg, typ=out_typ)


@_input_types("bytes_m", "int", "bytes")
def to_address(expr, arg, out_typ):
    # question: should this be allowed?
    if is_integer_type(arg.typ):
        if arg.typ._int_info.is_signed:
            _FAIL(arg.typ, out_typ, expr)

    return to_int(expr, arg, out_typ)


# question: should we allow bytesM -> String?
@_input_types("bytes")
def to_string(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # NOTE: this is a pointer cast
    return IRnode.from_list(arg, typ=out_typ)


@_input_types("string")
def to_bytes(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, out_typ.maxlen)

    # TODO: more casts

    # NOTE: this is a pointer cast
    return IRnode.from_list(arg, typ=out_typ)


@_input_types("int")
def to_enum(expr, arg, out_typ):
    if not is_base_type(arg.typ, "uint256"):
        _FAIL(arg.typ, out_typ, expr)

    if len(out_typ.members) < 256:
        arg = int_clamp(arg, bits=len(out_typ.members), signed=False)

    return IRnode.from_list(arg, typ=out_typ)


def convert(expr, context):
    if len(expr.args) != 2:
        raise StructureException("The convert function expects two parameters.", expr)

    arg_ast = expr.args[0]
    arg = Expr(arg_ast, context).ir_node
    original_arg = arg
    out_typ = context.parse_type(expr.args[1])

    if isinstance(arg.typ, BaseType):
        arg = unwrap_location(arg)
    with arg.cache_when_complex("arg") as (b, arg):
        if is_base_type(out_typ, "bool"):
            ret = to_bool(arg_ast, arg, out_typ)
        elif is_base_type(out_typ, "address"):
            ret = to_address(arg_ast, arg, out_typ)
        elif isinstance(out_typ, EnumType):
            ret = to_enum(arg_ast, arg, out_typ)
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

        # test if arg actually changed. if not, we do not need to use
        # unwrap_location (this can reduce memory traffic for downstream
        # operations which are in-place, like the returndata routine)
        test_arg = IRnode.from_list(arg, typ=out_typ)
        if test_arg == ret:
            original_arg.typ = out_typ
            return original_arg

        return IRnode.from_list(b.resolve(ret))
