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
    clamp_le,
    get_bytearray_length,
    int_clamp,
    is_bytes_m_type,
    is_decimal_type,
    is_flag_type,
    is_integer_type,
    sar,
    shl,
    shr,
    unwrap_location,
)
from vyper.codegen.expr import Expr
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidType,
    StructureException,
    TypeMismatch,
)
from vyper.semantics.types import (
    AddressT,
    BoolT,
    BytesM_T,
    BytesT,
    DecimalT,
    FlagT,
    IntegerT,
    StringT,
)
from vyper.semantics.types.bytestrings import _BytestringT
from vyper.semantics.types.shortcuts import INT256_T, UINT160_T, UINT256_T
from vyper.utils import DECIMAL_DIVISOR, round_towards_zero, unsigned_to_signed


def _FAIL(ityp, otyp, source_expr=None):
    # TODO consider changing this to InvalidType to be consistent
    # with the case when types are equal.
    raise TypeMismatch(f"Can't convert {ityp} to {otyp}", source_expr)


def _input_types(*allowed_types):
    def decorator(f):
        @functools.wraps(f)
        def check_input_type(expr, arg, out_typ):
            # convert arg to out_typ.
            # (expr is the AST corresponding to `arg`)
            ok = isinstance(arg.typ, allowed_types)
            if not ok:
                _FAIL(arg.typ, out_typ, expr)

            # user safety: disallow convert from type to itself
            # note allowance of [u]int256; this is due to type inference
            # on literals not quite working yet.
            if arg.typ == out_typ and arg.typ not in (UINT256_T, INT256_T):
                raise InvalidType(f"value and target are both {out_typ}", expr)

            return f(expr, arg, out_typ)

        return check_input_type

    return decorator


def _bytes_to_num(arg, out_typ, signed):
    # converting a bytestring to a number:
    # bytestring and bytes_m are right-padded with zeroes, int is left-padded.
    # convert by shr or sar the number of zero bytes (converted to bits)
    # e.g. "abcd000000000000" -> bitcast(000000000000abcd, output_type)

    if isinstance(arg.typ, _BytestringT):
        _len = get_bytearray_length(arg)
        arg = LOAD(bytes_data_ptr(arg))
        num_zero_bits = ["mul", 8, ["sub", 32, _len]]
    elif is_bytes_m_type(arg.typ):
        num_zero_bits = 8 * (32 - arg.typ.m)
    else:  # pragma: nocover
        raise CompilerPanic("unreachable")

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
        assert out_hi < 2**256 - 1, "bad assumption in numeric convert"
        arg = clamp_le(arg, out_hi, arg_is_signed)

    return arg


# truncate from fixed point decimal to int
def _fixed_to_int(arg, out_typ):
    DIVISOR = arg.typ.divisor

    # block inputs which are out of bounds before truncation.
    # e.g., convert(255.1, uint8) should revert or fail to compile.
    out_lo, out_hi = out_typ.int_bounds
    out_lo *= DIVISOR
    out_hi *= DIVISOR

    arg_bounds = arg.typ.int_bounds

    clamped_arg = _clamp_numeric_convert(arg, arg_bounds, (out_lo, out_hi), arg.typ.is_signed)

    assert arg.typ.is_signed, "should use unsigned div"  # stub for when we ufixed
    return IRnode.from_list(["sdiv", clamped_arg, DIVISOR], typ=out_typ)


# promote from int to fixed point decimal
def _int_to_fixed(arg, out_typ):
    DIVISOR = out_typ.divisor

    # block inputs which are out of bounds before promotion
    out_lo, out_hi = out_typ.int_bounds
    out_lo = round_towards_zero(out_lo / decimal.Decimal(DIVISOR))
    out_hi = round_towards_zero(out_hi / decimal.Decimal(DIVISOR))

    arg_bounds = arg.typ.int_bounds

    clamped_arg = _clamp_numeric_convert(arg, arg_bounds, (out_lo, out_hi), arg.typ.is_signed)

    return IRnode.from_list(["mul", clamped_arg, DIVISOR], typ=out_typ)


# clamp for dealing with conversions between int types (from arg to dst)
def _int_to_int(arg, out_typ):
    # do the same thing as
    # _clamp_numeric_convert(arg, arg.typ.int_bounds, out_typ.int_bounds, arg.typ.is_signed)
    # but with better code size and gas.
    if arg.typ.is_signed and not out_typ.is_signed:
        # e.g. (clample (clampge arg 0) (2**128 - 1))

        # note that when out_typ.bits == 256,
        # (clample arg 2**256 - 1) does not make sense.
        # see similar assertion in _clamp_numeric_convert.

        if out_typ.bits < arg.typ.bits:
            assert out_typ.bits < 256, "unreachable"
            # note: because of the usage of signed=False, and the fact
            # that out_bits < 256 in this branch, below implies
            # not only (clample arg 2**128 - 1) but also (clampge arg 0).
            arg = int_clamp(arg, out_typ.bits, signed=False)

        else:
            # note: this also works for out_bits == 256.
            arg = clamp("sge", arg, 0)

    elif not arg.typ.is_signed and out_typ.is_signed:
        # e.g. (uclample (uclampge arg 0) (2**127 - 1))
        # (note that (uclampge arg 0) always evaluates to true.)
        arg = int_clamp(arg, out_typ.bits - 1, signed=False)

    elif out_typ.bits < arg.typ.bits:
        assert out_typ.bits < 256, "unreachable"
        # narrowing conversion, signs are the same.
        # we can just use regular int clampers.
        arg = int_clamp(arg, out_typ.bits, out_typ.is_signed)

    else:
        # widening conversion, signs are the same.
        # we do not have to do any clamps.
        assert arg.typ.is_signed == out_typ.is_signed and out_typ.bits >= arg.typ.bits

    return IRnode.from_list(arg, typ=out_typ)


def _check_bytes(expr, arg, output_type, max_bytes_allowed):
    if isinstance(arg.typ, _BytestringT):
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
        assert len(expr.value[2:]) // 2 == arg_typ.m
        n_bits = arg_typ.m_bits
    else:
        assert len(expr.value) == arg_typ.maxlen
        n_bits = arg_typ.maxlen * 8

    return unsigned_to_signed(val, n_bits)


def _literal_int(expr, arg_typ, out_typ):
    # TODO: possible to reuse machinery from expr.py?
    if isinstance(expr, vy_ast.Hex):
        val = int(expr.value, 16)
    elif isinstance(expr, (vy_ast.Bytes, vy_ast.HexBytes)):
        val = int.from_bytes(expr.value, "big")
    elif isinstance(expr, (vy_ast.Int, vy_ast.Decimal, vy_ast.NameConstant)):
        val = expr.value
    else:  # pragma: no cover
        raise CompilerPanic("unreachable")

    if isinstance(expr, (vy_ast.Hex, vy_ast.Bytes, vy_ast.HexBytes)) and out_typ.is_signed:
        val = _signextend(expr, val, arg_typ)

    lo, hi = out_typ.int_bounds
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
        assert isinstance(expr.value, int)
        val *= DECIMAL_DIVISOR

    # sanity check type checker did its job
    assert math.ceil(val) == math.floor(val)

    val = int(val)

    # apply sign extension, if expected
    if isinstance(expr, vy_ast.Hex) and out_typ.is_signed:
        val = _signextend(expr, val, arg_typ)

    lo, hi = out_typ.int_bounds
    if not lo <= val <= hi:
        raise InvalidLiteral("Number out of range", expr)

    return IRnode.from_list(val, typ=out_typ)


# any base type or bytes/string
@_input_types(IntegerT, DecimalT, BytesM_T, AddressT, BoolT, BytesT, StringT)
def to_bool(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, 32)  # should we restrict to Bytes[1]?

    if isinstance(arg.typ, _BytestringT):
        # no clamp. checks for any nonzero bytes.
        arg = _bytes_to_num(arg, out_typ, signed=False)

    # NOTE: for decimal, the behavior is x != 0.0,
    # (we do not issue an `sdiv DECIMAL_DIVISOR`)

    return IRnode.from_list(["iszero", ["iszero", arg]], typ=out_typ)


@_input_types(IntegerT, DecimalT, BytesM_T, AddressT, BoolT, FlagT, BytesT)
def to_int(expr, arg, out_typ):
    return _to_int(expr, arg, out_typ)


# an internal version of to_int without input validation
def _to_int(expr, arg, out_typ):
    assert out_typ.bits % 8 == 0
    _check_bytes(expr, arg, out_typ, 32)

    if isinstance(expr, vy_ast.Constant):
        return _literal_int(expr, arg.typ, out_typ)

    elif isinstance(arg.typ, BytesT):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=out_typ.is_signed)
        if arg_typ.maxlen * 8 > out_typ.bits:
            arg = int_clamp(arg, out_typ.bits, signed=out_typ.is_signed)

    elif is_bytes_m_type(arg.typ):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=out_typ.is_signed)
        if arg_typ.m_bits > out_typ.bits:
            arg = int_clamp(arg, out_typ.bits, signed=out_typ.is_signed)

    elif is_decimal_type(arg.typ):
        arg = _fixed_to_int(arg, out_typ)

    elif is_flag_type(arg.typ):
        if out_typ != UINT256_T:
            _FAIL(arg.typ, out_typ, expr)
        # pretend flag is uint256
        arg = IRnode.from_list(arg, typ=UINT256_T)
        # use int_to_int rules
        arg = _int_to_int(arg, out_typ)

    elif is_integer_type(arg.typ):
        arg = _int_to_int(arg, out_typ)

    elif arg.typ == AddressT():
        if out_typ.is_signed:
            # TODO if possible, refactor to move this validation close to the entry of the function
            _FAIL(arg.typ, out_typ, expr)
        if out_typ.bits < 160:
            arg = int_clamp(arg, out_typ.bits, signed=False)

    return IRnode.from_list(arg, typ=out_typ)


@_input_types(IntegerT, BoolT, BytesM_T, BytesT)
def to_decimal(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, 32)

    if isinstance(expr, vy_ast.Constant):
        return _literal_decimal(expr, arg.typ, out_typ)

    if isinstance(arg.typ, BytesT):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=True)
        if arg_typ.maxlen * 8 > 168:
            arg = IRnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)

        return IRnode.from_list(arg, typ=out_typ)

    elif is_bytes_m_type(arg.typ):
        arg_typ = arg.typ
        arg = _bytes_to_num(arg, out_typ, signed=True)
        if arg_typ.m_bits > 168:
            arg = IRnode.from_list(arg, typ=out_typ)
            arg = clamp_basetype(arg)

        return IRnode.from_list(arg, typ=out_typ)

    elif is_integer_type(arg.typ):
        arg = _int_to_fixed(arg, out_typ)
        return IRnode.from_list(arg, typ=out_typ)

    elif arg.typ == BoolT():
        # TODO: consider adding is_signed and bits to bool so we can use _int_to_fixed
        arg = ["mul", arg, 10**out_typ.decimals]
        return IRnode.from_list(arg, typ=out_typ)
    else:  # pragma: nocover
        raise CompilerPanic("unreachable")


@_input_types(IntegerT, DecimalT, BytesM_T, AddressT, BytesT, BoolT)
def to_bytes_m(expr, arg, out_typ):
    _check_bytes(expr, arg, out_typ, max_bytes_allowed=out_typ.m)

    if isinstance(arg.typ, BytesT):
        bytes_val = LOAD(bytes_data_ptr(arg))

        # zero out any dirty bytes (which can happen in the last
        # word of a bytearray)
        len_ = get_bytearray_length(arg)
        num_zero_bits = IRnode.from_list(["mul", ["sub", 32, len_], 8])
        with num_zero_bits.cache_when_complex("bits") as (b, num_zero_bits):
            arg = shl(num_zero_bits, shr(num_zero_bits, bytes_val))
            arg = b.resolve(arg)

    elif is_bytes_m_type(arg.typ):
        # clamp if it's a downcast
        if arg.typ.m > out_typ.m:
            arg = bytes_clamp(arg, out_typ.m)

    elif is_integer_type(arg.typ) or arg.typ == AddressT():
        if arg.typ == AddressT():
            int_bits = 160
        else:
            int_bits = arg.typ.bits

        if out_typ.m_bits < int_bits:
            # question: allow with runtime clamp?
            # arg = int_clamp(m_bits, signed=arg.typ.signed)
            _FAIL(arg.typ, out_typ, expr)

        # note: neg numbers not OOB. keep sign bit
        arg = shl(256 - out_typ.m_bits, arg)

    elif is_decimal_type(arg.typ):
        if out_typ.m_bits < arg.typ.bits:
            _FAIL(arg.typ, out_typ, expr)

        # note: neg numbers not OOB. keep sign bit
        arg = shl(256 - out_typ.m_bits, arg)

    else:
        # bool
        arg = shl(256 - out_typ.m_bits, arg)

    return IRnode.from_list(arg, typ=out_typ)


@_input_types(BytesM_T, IntegerT, BytesT)
def to_address(expr, arg, out_typ):
    # question: should this be allowed?
    if is_integer_type(arg.typ):
        if arg.typ.is_signed:
            _FAIL(arg.typ, out_typ, expr)

    ret = _to_int(expr, arg, UINT160_T)
    return IRnode.from_list(ret, out_typ)


def _cast_bytestring(expr, arg, out_typ):
    # ban converting Bytes[20] to Bytes[21]
    if isinstance(arg.typ, out_typ.__class__) and arg.typ.maxlen <= out_typ.maxlen:
        _FAIL(arg.typ, out_typ, expr)
    # can't downcast literals with known length (e.g. b"abc" to Bytes[2])
    if isinstance(expr, vy_ast.Constant) and arg.typ.maxlen > out_typ.maxlen:
        _FAIL(arg.typ, out_typ, expr)

    ret = ["seq"]
    if out_typ.maxlen < arg.typ.maxlen:
        ret.append(["assert", ["le", get_bytearray_length(arg), out_typ.maxlen]])
    ret.append(arg)
    # NOTE: this is a pointer cast
    return IRnode.from_list(ret, typ=out_typ, location=arg.location, encoding=arg.encoding)


# question: should we allow bytesM -> String?
@_input_types(BytesT, StringT)
def to_string(expr, arg, out_typ):
    return _cast_bytestring(expr, arg, out_typ)


@_input_types(StringT, BytesT)
def to_bytes(expr, arg, out_typ):
    return _cast_bytestring(expr, arg, out_typ)


@_input_types(IntegerT)
def to_flag(expr, arg, out_typ):
    if arg.typ != UINT256_T:
        _FAIL(arg.typ, out_typ, expr)

    if len(out_typ._flag_members) < 256:
        arg = int_clamp(arg, bits=len(out_typ._flag_members), signed=False)

    return IRnode.from_list(arg, typ=out_typ)


def convert(expr, context):
    assert len(expr.args) == 2, "bad typecheck: convert"

    arg_ast = expr.args[0].reduced()
    arg = Expr(arg_ast, context).ir_node
    original_arg = arg

    out_typ = expr.args[1]._metadata["type"].typedef

    if arg.typ._is_prim_word:
        arg = unwrap_location(arg)
    with arg.cache_when_complex("arg") as (b, arg):
        if out_typ == BoolT():
            ret = to_bool(arg_ast, arg, out_typ)
        elif out_typ == AddressT():
            ret = to_address(arg_ast, arg, out_typ)
        elif is_flag_type(out_typ):
            ret = to_flag(arg_ast, arg, out_typ)
        elif is_integer_type(out_typ):
            ret = to_int(arg_ast, arg, out_typ)
        elif is_bytes_m_type(out_typ):
            ret = to_bytes_m(arg_ast, arg, out_typ)
        elif is_decimal_type(out_typ):
            ret = to_decimal(arg_ast, arg, out_typ)
        elif isinstance(out_typ, BytesT):
            ret = to_bytes(arg_ast, arg, out_typ)
        elif isinstance(out_typ, StringT):
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
