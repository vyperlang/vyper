"""
Shared arithmetic utilities for safe integer bounds computation.

These are pure math functions with no dependency on IR types.
If codegen_legacy is removed, consider moving to vyper/arithmetic.py
or vyper/utils/.
"""

import decimal
import math
from typing import Tuple

from vyper.exceptions import CompilerPanic, TypeCheckFailure


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
