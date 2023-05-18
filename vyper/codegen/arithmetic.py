import decimal
import math
from typing import Tuple

from vyper.codegen.core import (
    clamp,
    clamp_basetype,
    is_decimal_type,
    is_integer_type,
    is_numeric_type,
)
from vyper.codegen.ir_node import IRnode
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic, TypeCheckFailure, UnimplementedException


def calculate_largest_power(a: int, num_bits: int, is_signed: bool) -> int:
    """
    For a given base `a`, compute the maximum power `b` that will not
    produce an overflow in the equation `a ** b`

    Arguments
    ---------
    a : int
        Base value for the equation `a ** b`
    num_bits : int
        The maximum number of bits that the resulting value must fit in
    is_signed : bool
        Is the operation being performed on signed integers?

    Returns
    -------
    int
        Largest possible value for `b` where the result does not overflow
        `num_bits`
    """
    if num_bits % 8:  # pragma: no cover
        raise CompilerPanic("Type is not a modulo of 8")

    if a in (-1, 0, 1):  # pragma: no cover
        raise CompilerPanic("Exponential operation is useless!")

    value_bits = num_bits - (1 if is_signed else 0)
    if a >= 2**value_bits:  # pragma: no cover
        raise TypeCheckFailure("Value is too large and will always throw")
    if a < -(2**value_bits):  # pragma: no cover
        raise TypeCheckFailure("Value is too small and will always throw")

    a_is_negative = a < 0

    a = abs(a)  # No longer need to know if it's signed or not

    # NOTE: There is an edge case if `a` were left signed where the following
    #       operation would not work (`ln(a)` is undefined if `a <= 0`)
    b = int(decimal.Decimal(value_bits) / (decimal.Decimal(a).ln() / decimal.Decimal(2).ln()))
    if b <= 1:
        return 1  # Value is assumed to be in range, therefore power of 1 is max

    # Do a bit of iteration to ensure we have the exact number

    # CMC 2022-05-06 (TODO we should be able to this with algebra
    # instead of looping):
    # a ** x == 2**value_bits
    # x ln(a) = ln(2**value_bits)
    # x = ln(2**value_bits) / ln(a)

    num_iterations = 0
    while a ** (b + 1) < 2**value_bits:
        b += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a**b >= 2**value_bits:
        b -= 1
        num_iterations += 1
        assert num_iterations < 10000

    # Edge case: If a is negative and the values of a and b are such that:
    #   (-a) ** (b + 1) == -(2 ** value_bits)
    # we can squeak one more out of it because lower bound of signed ints
    # is slightly wider than upper bound
    if a_is_negative and (-a) ** (b + 1) == -(2**value_bits):  # NOTE: a = abs(a)
        return b + 1
    else:
        return b  # Exact


def calculate_largest_base(b: int, num_bits: int, is_signed: bool) -> Tuple[int, int]:
    """
    For a given power `b`, compute the maximum base `a` that will not produce an
    overflow in the equation `a ** b`

    Arguments
    ---------
    b : int
        Power value for the equation `a ** b`
    num_bits : int
        The maximum number of bits that the resulting value must fit in
    is_signed : bool
        Is the operation being performed on signed integers?

    Returns
    -------
    Tuple[int, int]
        Smallest and largest possible values for `a` where the result
        does not overflow `num_bits`.

        Note that the lower and upper bounds are not always negatives of
        each other, due to lower/upper bounds for int_<value_bits> being
        slightly asymmetric.
    """
    if num_bits % 8:  # pragma: no cover
        raise CompilerPanic("Type is not a modulo of 8")

    if b in (0, 1):  # pragma: no cover
        raise CompilerPanic("Exponential operation is useless!")

    if b < 0:  # pragma: no cover
        raise TypeCheckFailure("Cannot calculate negative exponents")

    value_bits = num_bits - (1 if is_signed else 0)
    if b > value_bits:  # pragma: no cover
        raise TypeCheckFailure("Value is too large and will always throw")

    # CMC 2022-05-06 TODO we should be able to do this with algebra
    # instead of looping):
    # x ** b == 2**value_bits
    # b ln(x) == ln(2**value_bits)
    # ln(x) == ln(2**value_bits) / b
    # x == exp( ln(2**value_bits) / b)

    # Estimate (up to ~39 digits precision required)
    a = math.ceil(2 ** (decimal.Decimal(value_bits) / decimal.Decimal(b)))
    # Do a bit of iteration to ensure we have the exact number
    num_iterations = 0
    while (a + 1) ** b < 2**value_bits:
        a += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a**b >= 2**value_bits:
        a -= 1
        num_iterations += 1
        assert num_iterations < 10000

    if not is_signed:
        return 0, a

    if (a + 1) ** b == (2**value_bits):
        # edge case: lower bound is slightly wider than upper bound
        return -(a + 1), a
    else:
        return -a, a


# def safe_add(x: IRnode, y: IRnode) -> IRnode:
def safe_add(x, y):
    assert x.typ is not None and x.typ == y.typ and is_numeric_type(x.typ)
    typ = x.typ

    res = IRnode.from_list(["add", x, y], typ=typ)

    if typ.bits < 256:
        return clamp_basetype(res)

    # bits == 256
    with res.cache_when_complex("ans") as (b1, res):
        if typ.is_signed:
            # if r < 0:
            #   ans < l
            # else:
            #   ans >= l  # aka (iszero (ans < l))
            # aka: (r < 0) == (ans < l)
            ok = ["eq", ["slt", y, 0], ["slt", res, x]]
        else:
            # note this is "equivalent" to the unsigned form
            # of the above (because y < 0 == False)
            #       ["eq", ["lt", y, 0], ["lt", res, x]]
            # TODO push down into optimizer rules.
            ok = ["ge", res, x]

        check = IRnode.from_list(["assert", ok], error_msg="safeadd")
        ret = IRnode.from_list(["seq", check, res])
        return b1.resolve(ret)


# def safe_sub(x: IRnode, y: IRnode) -> IRnode:
def safe_sub(x, y):
    assert x.typ == y.typ
    typ = x.typ

    res = IRnode.from_list(["sub", x, y], typ=typ)

    if typ.bits < 256:
        return clamp_basetype(res)

    # bits == 256
    with res.cache_when_complex("ans") as (b1, res):
        if typ.is_signed:
            # if r < 0:
            #   ans > l
            # else:
            #   ans <= l  # aka (iszero (ans > l))
            # aka: (r < 0) == (ans > l)
            ok = ["eq", ["slt", y, 0], ["sgt", res, x]]
        else:
            # note this is "equivalent" to the unsigned form
            # of the above (because y < 0 == False)
            #       ["eq", ["lt", y, 0], ["gt", res, x]]
            # TODO push down into optimizer rules.
            ok = ["le", res, x]

        check = IRnode.from_list(["assert", ok], error_msg="safesub")
        ret = IRnode.from_list(["seq", check, res])
        return b1.resolve(ret)


# def safe_mul(x: IRnode, y: IRnode) -> IRnode:
def safe_mul(x, y):
    # precondition: x.typ == y.typ
    assert x.typ == y.typ
    typ = x.typ

    # optimizer rules work better for the safemul checks below
    # if second operand is literal
    if x.is_literal:
        tmp = x
        x = y
        y = tmp

    res = IRnode.from_list(["mul", x, y], typ=x.typ)

    DIV = "sdiv" if typ.is_signed else "div"

    with res.cache_when_complex("ans") as (b1, res):
        ok = [1]  # True

        if typ.bits > 128:  # check overflow mod 256
            # assert (res/y == x | y == 0)
            ok = ["or", ["eq", [DIV, res, y], x], ["iszero", y]]

        # int256
        if typ.is_signed and typ.bits == 256:
            # special case:
            # in the above sdiv check, if (r==-1 and l==-2**255),
            # -2**255<res> / -1<r> will return -2**255<l>.
            # need to check: not (r == -1 and l == -2**255)
            if version_check(begin="constantinople"):
                upper_bound = ["shl", 255, 1]
            else:
                upper_bound = -(2**255)

            check_x = ["ne", x, upper_bound]
            check_y = ["ne", ["not", y], 0]

            if not x.is_literal and not y.is_literal:
                # TODO can simplify this condition?
                ok = ["and", ok, ["or", check_x, check_y]]

            # TODO push some of this constant folding into optimizer
            elif x.is_literal and x.value == -(2**255):
                ok = ["and", ok, check_y]
            elif y.is_literal and y.value == -1:
                ok = ["and", ok, check_x]
            else:
                # x or y is a literal, and we have determined it is
                # not an evil value
                pass

        if is_decimal_type(res.typ):
            res = IRnode.from_list([DIV, res, typ.divisor], typ=res.typ)

        # check overflow mod <bits>
        # NOTE: if 128 < bits < 256, `x * y` could be between
        # MAX_<bits> and 2**256 OR it could overflow past 2**256.
        # so, we check for overflow in mod 256 AS WELL AS mod <bits>
        # (if bits == 256, clamp_basetype is a no-op)
        res = clamp_basetype(res)

        check = IRnode.from_list(["assert", ok], error_msg="safemul")
        res = IRnode.from_list(["seq", check, res], typ=res.typ)

        return b1.resolve(res)


# def safe_div(x: IRnode, y: IRnode) -> IRnode:
def safe_div(x, y):
    assert x.typ == y.typ
    typ = x.typ

    ok = [1]  # true

    if is_decimal_type(x.typ):
        lo, hi = typ.int_bounds
        if max(abs(lo), abs(hi)) * typ.divisor > 2**256 - 1:
            # stub to prevent us from adding fixed point numbers we don't know
            # how to deal with
            raise UnimplementedException("safe_mul for decimal{typ.bits}x{typ.decimals}")
        x = ["mul", x, typ.divisor]

    DIV = "sdiv" if typ.is_signed else "div"
    res = IRnode.from_list([DIV, x, clamp("gt", y, 0)], typ=typ)
    with res.cache_when_complex("res") as (b1, res):
        # TODO: refactor this condition / push some things into the optimizer
        if typ.is_signed and typ.bits == 256:
            if version_check(begin="constantinople"):
                upper_bound = ["shl", 255, 1]
            else:
                upper_bound = -(2**255)

            if not x.is_literal and not y.is_literal:
                ok = ["or", ["ne", y, ["not", 0]], ["ne", x, upper_bound]]
            # TODO push these rules into the optimizer
            elif x.is_literal and x.value == -(2**255):
                ok = ["ne", y, ["not", 0]]
            elif y.is_literal and y.value == -1:
                ok = ["ne", x, upper_bound]
            else:
                # x or y is a literal, and not an evil value.
                pass

        elif typ.is_signed and is_integer_type(typ):
            lo, hi = typ.int_bounds
            # we need to throw on min_value(typ) / -1,
            # but we can skip if one of the operands is a literal and not
            # the evil value
            can_skip_clamp = (x.is_literal and x.value != lo) or (y.is_literal and y.value != -1)
            if not can_skip_clamp:
                # clamp_basetype has fewer ops than the int256 rule.
                res = clamp_basetype(res)

        elif is_decimal_type(typ):
            # always clamp decimals, since decimal division can actually
            # result in something larger than either operand (e.g. 1.0 / 0.1)
            # TODO maybe use safe_mul
            res = clamp_basetype(res)

        check = IRnode.from_list(["assert", ok], error_msg="safediv")
        return IRnode.from_list(b1.resolve(["seq", check, res]))


# def safe_mod(x: IRnode, y: IRnode) -> IRnode:
def safe_mod(x, y):
    typ = x.typ
    MOD = "smod" if typ.is_signed else "mod"
    return IRnode.from_list([MOD, x, clamp("gt", y, 0)], error_msg="safemod")


# def safe_pow(x: IRnode, y: IRnode) -> IRnode:
def safe_pow(x, y):
    typ = x.typ
    if not is_integer_type(x.typ):
        # type checker should have caught this
        raise TypeCheckFailure("non-integer pow")

    GE = "sge" if typ.is_signed else "ge"

    if x.is_literal:
        # cannot pass -1, 0 or 1 to `calculate_largest_power`
        if x.value in (-1, 0, 1):
            # not strictly needed, but consistent with other bases
            # (note: unsigned (ge y 0) will get optimized out)
            ok = [GE, y, 0]
        else:
            upper_bound = calculate_largest_power(x.value, typ.bits, typ.is_signed)
            # for signed integers, this also prevents negative values
            ok = ["le", y, upper_bound]

    elif y.is_literal:
        # cannot pass 0 or 1 to `calculate_largest_base`
        if y.value in (0, 1):
            ok = [1]
        else:
            lower_bound, upper_bound = calculate_largest_base(y.value, typ.bits, typ.is_signed)
            if typ.is_signed:
                ok = ["and", ["sge", x, lower_bound], ["sle", x, upper_bound]]
            else:
                ok = ["le", x, upper_bound]
    else:
        # `a ** b` where neither `a` or `b` are known
        # TODO this is currently unreachable, once we implement a way to do it safely
        # remove the check in `vyper/context/types/value/numeric.py`
        return

    assertion = IRnode.from_list(["assert", ok], error_msg="safepow")
    return IRnode.from_list(["seq", assertion, ["exp", x, y]])
