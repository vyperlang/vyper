from vyper.evm.opcodes import version_check
from vyper.codegen.ir_node import IRnode
from vyper.codegen.core import clamp_basetype, clamp
from vyper.codegen.types import is_integer_type, is_decimal_type
from vyper.exceptions import CompilerPanic
import math
import decimal


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
    if num_bits % 8:
        raise CompilerPanic("Type is not a modulo of 8")

    value_bits = num_bits - (1 if is_signed else 0)
    if a >= 2 ** value_bits:
        raise TypeCheckFailure("Value is too large and will always throw")
    elif a < -(2 ** value_bits):
        raise TypeCheckFailure("Value is too small and will always throw")

    a_is_negative = a < 0
    a = abs(a)  # No longer need to know if it's signed or not

    if a in (0, 1):
        raise CompilerPanic("Exponential operation is useless!")

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
    while a ** (b + 1) < 2 ** value_bits:
        b += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a ** b >= 2 ** value_bits:
        b -= 1
        num_iterations += 1
        assert num_iterations < 10000

    # Edge case: If a is negative and the values of a and b are such that:
    #               (a) ** (b + 1) == -(2 ** value_bits)
    #            we can actually squeak one more out of it because it's on the edge
    if a_is_negative and (-a) ** (b + 1) == -(2 ** value_bits):  # NOTE: a = abs(a)
        return b + 1
    else:
        return b  # Exact


def calculate_largest_base(b: int, num_bits: int, is_signed: bool) -> int:
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
    int
        Largest possible value for `a` where the result does not overflow
        `num_bits`
    """
    if num_bits % 8:
        raise CompilerPanic("Type is not a modulo of 8")
    if b < 0:
        raise TypeCheckFailure("Cannot calculate negative exponents")

    value_bits = num_bits - (1 if is_signed else 0)
    if b > value_bits:
        raise TypeCheckFailure("Value is too large and will always throw")
    elif b < 2:
        return 2 ** value_bits - 1  # Maximum value for type

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
    while (a + 1) ** b < 2 ** value_bits:
        a += 1
        num_iterations += 1
        assert num_iterations < 10000
    while a ** b >= 2 ** value_bits:
        a -= 1
        num_iterations += 1
        assert num_iterations < 10000
    return a


def safe_add(x: IRnode, y: IRnode):
    # precondition: x.typ.typ == t.typ.typ
    num_info = x.typ._num_info

    res = IRnode.from_list(["add", x, y], typ=x.typ.typ)

    if num_info.bits < 256:
        return clamp_basetype(res)

    # bits == 256
    with res.cache_when_complex("ans") as (b1, res):
        if num_info.is_signed:
            # if r < 0:
            #   ans < l
            # else:
            #   ans >= l  # aka (iszero (ans < l))
            # aka: (r < 0) == (ans < l)
            clamp = ["eq", ["slt", y, 0], ["slt", res, x]]
        else:
            # note this is "equivalent" to the unsigned form
            # of the above (because y < 0 == False)
            #       ["eq", ["lt", y, 0], ["lt", res, x]]
            clamp = ["ge", res, x]

        return b1.resolve(["seq", clamp, res])

    raise CompilerPanic("unreachable")  # pragma: notest


def safe_sub(x: IRnode, y: IRnode):
    num_info = x.typ._num_info

    res = IRnode.from_list(["sub", x, y], typ=x.typ.typ)

    if num_info.bits < 256:
        return clamp_basetype(res)

    # bits == 256
    with res.cache_when_complex("ans") as (b1, res):
        if num_info.is_signed:
            # if r < 0:
            #   ans > l
            # else:
            #   ans <= l  # aka (iszero (ans > l))
            # aka: (r < 0) == (ans > l)
            clamp = ["eq", ["slt", y, 0], ["sgt", res, x]]
        else:
            # note this is "equivalent" to the unsigned form
            # of the above (because y < 0 == False)
            #       ["eq", ["lt", y, 0], ["gt", res, x]]
            clamp = ["le", res, x]

        return b1.resolve(["seq", ["assert", clamp], res])

    raise CompilerPanic("unreachable")  # pragma: notest


def safe_mul(x: IRnode, y: IRnode):
    # precondition: x.typ.typ == y.typ.typ
    num_info = x.typ._num_info

    # optimizer rules work better if second operand is literal
    if x.is_literal:
        tmp = x
        x = y
        y = tmp

    res = IRnode.from_list(["mul", x, y], typ=x.typ.typ)

    DIV = "sdiv" if num_info.is_signed else "div"

    with res.cache_when_complex("ans") as (b1, res):

        ok = IRnode(1)  # true

        if num_info.bits > 128:  # check overflow mod 256
            # assert (res/l == r || l == 0)
            ok = ["or", ["eq", [DIV, res, y], x], ["iszero", y]]

        if num_info.bits == 256 and num_info.is_signed:
            # special case:
            # in the sdiv check, if (l==-1 and r==-2**255),
            # -2**255<res> / -1<l> will return -2**255<r>.
            # need to check for this case.
            if version_check(begin="constantinople"):
                upper_bound = ["shl", 255, 1]
            else:
                upper_bound = -(2 ** 255)

            if not x.is_literal and not y.is_literal:
                # TODO can simplify this condition?
                bounds_check = ["or", ["ne", x, ["not", 0]], ["ne", y, upper_bound]]

            # TODO push some of this constant folding into optimizer
            elif x.is_literal and x.value == -1:
                bounds_check = ["ne", y, upper_bound]
            elif y.is_literal and y.value == -(2 ** 255):
                bounds_check = ["ne", x, ["not", 0]]
            else:
                # trigger optimizer rule: -1 & x == x
                bounds_check = 2**256 - 1

            ok = ["and", bounds_check, ok]

        # check overflow mod <bits>
        # NOTE: if 128 < bits < 256, `x * y` could be between
        # MAX_<bits> and 2**256 OR it could overflow past 2**256. so,
        # we check for overflow in mod 256 AND mod <bits>
        # (if bits == 256, clamp_basetype is a no-op)
        res = clamp_basetype(res)

        if is_decimal_type(res.typ):
            res = IRnode.from_list([DIV, res, int(num_info.divisor)])

        res = IRnode.from_list(["seq", ["assert", ok], res], typ=res.typ)

        return b1.resolve(res)


def safe_div(x: IRnode, y: IRnode):
    num_info = x.typ._num_info

    ok = IRnode(1)  # true

    # TODO: refactor this condition / push some things into the optimizer
    if x.typ.typ == "int256":
        if version_check(begin="constantinople"):
            upper_bound = ["shl", 255, 1]
        else:
            upper_bound = -(2 ** 255)
        if not x.is_literal and not y.typ.is_literal:
            ok = ["or", ["ne", x, ["not", 0]], ["ne", y, upper_bound]]
        # TODO push this constant folding into the optimizer
        elif x.is_literal and x.value == -(2 ** 255):
            ok = ["ne", x, ["not", 0]]
        elif y.is_literal and y.value == -1:
            ok = ["ne", y, upper_bound]

    if is_decimal_type(x.typ):
        # TODO: if MAX_DECIMAL * 10**decimal could wrap, we would need
        # to do a bounds check.
        x = ["mul", x, int(num_info.divisor)]

    DIV = "sdiv" if num_info.is_signed else "div"
    return ["seq", ["assert", ok], [DIV, x, clamp("gt", y, 0)]]


def safe_mod(x: IRnode, y: IRnode):
    num_info = x.typ._num_info
    MOD = "smod" if num_info.is_signed else "mod"
    return ["seq", [MOD, x, clamp("gt", y, 0)]]


def safe_pow(x: IRnode, y: IRnode):
    num_info = x.typ._num_info

    if x.is_literal:
        upper_bound = calculate_largest_power(x.value, num_info.bits, num_info.is_signed) + 1
        # for signed integers, this also prevents negative values
        ok = ["lt", y, upper_bound]

    elif y.is_literal:
        upper_bound = calculate_largest_base(y.value, num_info.bits, num_info.is_signed) + 1
        if num_info.is_signed:
            ok = ["and", ["slt", x, upper_bound], ["sgt", x, -upper_bound]]
        else:
            ok = ["lt", x, upper_bound]
    else:
        # `a ** b` where neither `a` or `b` are known
        # TODO this is currently unreachable, once we implement a way to do it safely
        # remove the check in `vyper/context/types/value/numeric.py`
        return

    return ["seq", ["assert", ok], ["exp", x, y]]
