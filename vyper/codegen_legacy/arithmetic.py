import decimal
import math
from typing import Tuple

from vyper.codegen_legacy.core import (
    clamp,
    clamp_basetype,
    is_decimal_type,
    is_integer_type,
    is_numeric_type,
)
from vyper.codegen_legacy.ir_node import IRnode
from vyper.codegen_shared.arithmetic import (
    calculate_largest_base,
    calculate_largest_power,
)
from vyper.exceptions import CompilerPanic, TypeCheckFailure, UnimplementedException


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
            upper_bound = ["shl", 255, 1]

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
        if max(abs(lo), abs(hi)) * typ.divisor > 2**256 - 1:  # pragma: nocover
            # stub to prevent us from adding fixed point numbers we don't know
            # how to deal with
            raise UnimplementedException(f"safe_mul for decimal{typ.bits}x{typ.decimals}")
        x = ["mul", x, typ.divisor]

    DIV = "sdiv" if typ.is_signed else "div"
    res = IRnode.from_list([DIV, x, clamp("gt", y, 0)], typ=typ)
    with res.cache_when_complex("res") as (b1, res):
        # TODO: refactor this condition / push some things into the optimizer
        if typ.is_signed and typ.bits == 256:
            upper_bound = ["shl", 255, 1]

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
    # TODO: (force) propagate safemod error msg down to all children,
    # overriding the "clamp" error msg.
    return IRnode.from_list([MOD, x, clamp("gt", y, 0)], error_msg="safemod")


# def safe_pow(x: IRnode, y: IRnode) -> IRnode:
def safe_pow(x, y):
    typ = x.typ
    if not is_integer_type(x.typ):  # pragma: nocover
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
