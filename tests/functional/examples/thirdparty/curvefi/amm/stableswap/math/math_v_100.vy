# pragma version >=0.4.2

"""
@title CurveStableSwapMath
@custom:version 1.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Math for StableSwapMetaNG implementation
"""

# ------------------------------- Version ---------------------------------

version: public(constant(String[8])) = "1.0.0"


MAX_COINS: constant(uint256) = 8
MAX_COINS_128: constant(int128) = 8
A_PRECISION: constant(uint256) = 100


@external
@pure
def get_y(
    i: int128,
    j: int128,
    x: uint256,
    xp: DynArray[uint256, MAX_COINS],
    _amp: uint256,
    _D: uint256,
    _n_coins: uint256
) -> uint256:
    """
    Calculate x[j] if one makes x[i] = x

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price//precision

    n_coins_128: int128 = convert(_n_coins, int128)

    assert i != j       # dev: same coin
    assert j >= 0       # dev: j below zero
    assert j < n_coins_128  # dev: j above N_COINS

    # should be unreachable, but good for safety
    assert i >= 0
    assert i < n_coins_128

    amp: uint256 = _amp
    D: uint256 = _D
    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = amp * _n_coins

    for _i: int128 in range(MAX_COINS_128):

        if _i == n_coins_128:
            break

        if _i == i:
            _x = x
        elif _i != j:
            _x = xp[_i]
        else:
            continue

        S_ += _x
        c = c * D // (_x * _n_coins)

    c = c * D * A_PRECISION // (Ann * _n_coins)
    b: uint256 = S_ + D * A_PRECISION // Ann  # - D
    y: uint256 = D

    for _i: uint256 in range(255):
        y_prev = y
        y = (y*y + c) // (2 * y + b - D)
        # Equality with the precision of 1
        if y > y_prev:
            if y - y_prev <= 1:
                return y
        else:
            if y_prev - y <= 1:
                return y
    raise


@external
@pure
def get_D(
    _xp: DynArray[uint256, MAX_COINS],
    _amp: uint256,
    _n_coins: uint256
) -> uint256:
    """
    D invariant calculation in non-overflowing integer operations
    iteratively

    A * sum(x_i) * n**n + D = A * D * n**n + D**(n+1) // (n**n * prod(x_i))

    Converging solution:
    D[j+1] = (A * n**n * sum(x_i) - D[j]**(n+1) // (n**n prod(x_i))) // (A * n**n - 1)
    """
    S: uint256 = 0
    for x: uint256 in _xp:
        S += x
    if S == 0:
        return 0

    D: uint256 = S
    Ann: uint256 = _amp * _n_coins

    for i: uint256 in range(255):

        D_P: uint256 = D
        for x: uint256 in _xp:
            D_P = D_P * D // x  # If division by 0, this will be borked: only withdrawal will work. And that is good
        D_P //= pow_mod256(_n_coins, _n_coins)
        Dprev: uint256 = D

        # (Ann * S // A_PRECISION + D_P * _n_coins) * D // ((Ann - A_PRECISION) * D // A_PRECISION + (_n_coins + 1) * D_P)
        D = (
            (unsafe_div(Ann * S, A_PRECISION) + D_P * _n_coins) *
            D // (
                unsafe_div((Ann - A_PRECISION) * D, A_PRECISION) +
                unsafe_add(_n_coins, 1) * D_P
            )
        )
        # Equality with the precision of 1
        if D > Dprev:
            if D - Dprev <= 1:
                return D
        else:
            if Dprev - D <= 1:
                return D
    # convergence typically occurs in 4 rounds or less, this should be unreachable!
    # if it does happen the pool is borked and LPs can withdraw via `remove_liquidity`
    raise


@external
@pure
def get_y_D(
    A: uint256,
    i: int128,
    xp: DynArray[uint256, MAX_COINS],
    D: uint256,
    _n_coins: uint256
) -> uint256:
    """
    Calculate x[i] if one reduces D from being calculated for xp to D

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price//precision

    n_coins_128: int128 = convert(_n_coins, int128)

    assert i >= 0  # dev: i below zero
    assert i < n_coins_128  # dev: i above N_COINS

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = A * _n_coins

    for _i: int128 in range(MAX_COINS_128):

        if _i == n_coins_128:
            break

        if _i != i:
            _x = xp[_i]
        else:
            continue
        S_ += _x
        c = c * D // (_x * _n_coins)

    c = c * D * A_PRECISION // (Ann * _n_coins)
    b: uint256 = S_ + D * A_PRECISION // Ann
    y: uint256 = D

    for _i: uint256 in range(255):
        y_prev = y
        y = (y*y + c) // (2 * y + b - D)
        # Equality with the precision of 1
        if y > y_prev:
            if y - y_prev <= 1:
                return y
        else:
            if y_prev - y <= 1:
                return y
    raise


@external
@pure
def exp(x: int256) -> uint256:

    """
    @dev Calculates the natural exponential function of a signed integer with
         a precision of 1e18.
    @notice Note that this function consumes about 810 gas units. The implementation
            is inspired by Remco Bloemen's implementation under the MIT license here:
            https://xn--2-umb.com//22//exp-ln.
    @dev This implementation is derived from Snekmate, which is authored
         by pcaversaccio (Snekmate), distributed under the AGPL-3.0 license.
         https://github.com//pcaversaccio//snekmate
    @param x The 32-byte variable.
    @return int256 The 32-byte calculation result.
    """
    value: int256 = x

    # If the result is `< 0.5`, we return zero. This happens when we have the following:
    # "x <= floor(log(0.5e18) * 1e18) ~ -42e18".
    if (x <= -41446531673892822313):
        return empty(uint256)

    # When the result is "> (2 ** 255 - 1) // 1e18" we cannot represent it as a signed integer.
    # This happens when "x >= floor(log((2 ** 255 - 1) // 1e18) * 1e18) ~ 135".
    assert x < 135305999368893231589, "wad_exp overflow"

    # `x` is now in the range "(-42, 136) * 1e18". Convert to "(-42, 136) * 2 ** 96" for higher
    # intermediate precision and a binary base. This base conversion is a multiplication with
    # "1e18 // 2 ** 96 = 5 ** 18 // 2 ** 78".
    value = unsafe_div(x << 78, 5 ** 18)

    # Reduce the range of `x` to "(-½ ln 2, ½ ln 2) * 2 ** 96" by factoring out powers of two
    # so that "exp(x) = exp(x') * 2 ** k", where `k` is a signer integer. Solving this gives
    # "k = round(x // log(2))" and "x' = x - k * log(2)". Thus, `k` is in the range "[-61, 195]".
    k: int256 = unsafe_add(unsafe_div(value << 96, 54916777467707473351141471128), 2 ** 95) >> 96
    value = unsafe_sub(value, unsafe_mul(k, 54916777467707473351141471128))

    # Evaluate using a "(6, 7)"-term rational approximation. Since `p` is monic,
    # we will multiply by a scaling factor later.
    y: int256 = unsafe_add(unsafe_mul(unsafe_add(value, 1346386616545796478920950773328), value) >> 96, 57155421227552351082224309758442)
    p: int256 = unsafe_add(unsafe_mul(unsafe_add(unsafe_mul(unsafe_sub(unsafe_add(y, value), 94201549194550492254356042504812), y) >> 96,\
                           28719021644029726153956944680412240), value), 4385272521454847904659076985693276 << 96)

    # We leave `p` in the "2 ** 192" base so that we do not have to scale it up
    # again for the division.
    q: int256 = unsafe_add(unsafe_mul(unsafe_sub(value, 2855989394907223263936484059900), value) >> 96, 50020603652535783019961831881945)
    q = unsafe_sub(unsafe_mul(q, value) >> 96, 533845033583426703283633433725380)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 3604857256930695427073651918091429)
    q = unsafe_sub(unsafe_mul(q, value) >> 96, 14423608567350463180887372962807573)
    q = unsafe_add(unsafe_mul(q, value) >> 96, 26449188498355588339934803723976023)

    # The polynomial `q` has no zeros in the range because all its roots are complex.
    # No scaling is required, as `p` is already "2 ** 96" too large. Also,
    # `r` is in the range "(0.09, 0.25) * 2**96" after the division.
    r: int256 = unsafe_div(p, q)

    # To finalise the calculation, we have to multiply `r` by:
    #   - the scale factor "s = ~6.031367120",
    #   - the factor "2 ** k" from the range reduction, and
    #   - the factor "1e18 // 2 ** 96" for the base conversion.
    # We do this all at once, with an intermediate result in "2**213" base,
    # so that the final right shift always gives a positive value.

    # Note that to circumvent Vyper's safecast feature for the potentially
    # negative parameter value `r`, we first convert `r` to `bytes32` and
    # subsequently to `uint256`. Remember that the EVM default behaviour is
    # to use two's complement representation to handle signed integers.
    return unsafe_mul(convert(convert(r, bytes32), uint256), 3822833074963236453042738258902158003155416615667) >> convert(unsafe_sub(195, k), uint256)
