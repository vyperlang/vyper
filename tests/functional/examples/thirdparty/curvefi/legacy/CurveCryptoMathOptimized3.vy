# adapted from https://github.com/curvefi/tricrypto-ng/blob/584591e6613cb6cdb46e4659488a8cccdfff69ad/contracts/main/CurveCryptoMathOptimized3.vy

"""
@title CurveTricryptoMathOptimized
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice Curve AMM Math for 3 unpegged assets (e.g. ETH, BTC, USD).
"""

N_COINS: constant(uint256) = 3
A_MULTIPLIER: constant(uint256) = 10000

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 5 * 10**16

MIN_A: constant(uint256) = (N_COINS**N_COINS) * A_MULTIPLIER // 100
MAX_A: constant(uint256) = (N_COINS**N_COINS) * A_MULTIPLIER * 1000

version: public(constant(String[8])) = "v2.0.0"


# ------------------------ AMM math functions --------------------------------


@external
@view
def get_y(
    _ANN: uint256, _gamma: uint256, x: uint256[N_COINS], _D: uint256, i: uint256
) -> uint256[2]:
    """
    @notice Calculate x[i] given other balances x[0..N_COINS-1] and invariant D.
    @dev ANN = A * N**N.
    @param _ANN AMM.A() value.
    @param _gamma AMM.gamma() value.
    @param x Balances multiplied by prices and precisions of all coins.
    @param _D Invariant.
    @param i Index of coin to calculate y.
    """

    # Safety checks
    assert _ANN > MIN_A - 1 and _ANN < MAX_A + 1  # dev: unsafe values A
    assert _gamma > MIN_GAMMA - 1 and _gamma < MAX_GAMMA + 1  # dev: unsafe values gamma
    assert _D > 10**17 - 1 and _D < 10**15 * 10**18 + 1  # dev: unsafe values D

    frac: uint256 = 0
    for k: uint256 in range(3):
        if k != i:
            frac = x[k] * 10**18 // _D
            assert frac > 10**16 - 1 and frac < 10**20 + 1, "Unsafe values x[i]"
            # if above conditions are met, x[k] > 0

    j: uint256 = 0
    k: uint256 = 0
    if i == 0:
        j = 1
        k = 2
    elif i == 1:
        j = 0
        k = 2
    elif i == 2:
        j = 0
        k = 1

    ANN: int256 = convert(_ANN, int256)
    gamma: int256 = convert(_gamma, int256)
    D: int256 = convert(_D, int256)
    x_j: int256 = convert(x[j], int256)
    x_k: int256 = convert(x[k], int256)
    gamma2: int256 = unsafe_mul(gamma, gamma)

    a: int256 = 10**36 // 27

    # 10**36/9 + 2*10**18*gamma/27 - D**2/x_j*gamma**2*ANN/27**2/convert(A_MULTIPLIER, int256)/x_k
    b: int256 = (
        unsafe_add(
            10**36 // 9,
            unsafe_div(unsafe_mul(2 * 10**18, gamma), 27)
        )
        - unsafe_div(
            unsafe_div(
                unsafe_div(
                    unsafe_mul(
                        unsafe_div(unsafe_mul(D, D), x_j),
                        gamma2
                    ) * ANN,
                    27**2
                ),
                convert(A_MULTIPLIER, int256)
            ),
            x_k,
        )
    )  # <------- The first two expressions can be unsafe, and unsafely added.

    # 10**36/9 + gamma*(gamma + 4*10**18)/27 + gamma**2*(x_j+x_k-D)/D*ANN/27/convert(A_MULTIPLIER, int256)
    c: int256 = (
        unsafe_add(
            10**36 // 9,
            unsafe_div(unsafe_mul(gamma, unsafe_add(gamma, 4 * 10**18)), 27)
        )
        + unsafe_div(
            unsafe_div(
                unsafe_mul(
                    unsafe_div(gamma2 * unsafe_sub(unsafe_add(x_j, x_k), D), D),
                    ANN
                ),
                27
            ),
            convert(A_MULTIPLIER, int256),
        )
    )  # <--------- Same as above with the first two expressions. In the third
    #   expression, x_j + x_k will not overflow since we know their range from
    #                                              previous assert statements.

    # (10**18 + gamma)**2/27
    d: int256 = unsafe_div(unsafe_add(10**18, gamma)**2, 27)

    # abs(3*a*c/b - b)
    d0: int256 = abs(unsafe_mul(3, a) * c // b - b)  # <------------ a is smol.

    divider: int256 = 0
    if d0 > 10**48:
        divider = 10**30
    elif d0 > 10**44:
        divider = 10**26
    elif d0 > 10**40:
        divider = 10**22
    elif d0 > 10**36:
        divider = 10**18
    elif d0 > 10**32:
        divider = 10**14
    elif d0 > 10**28:
        divider = 10**10
    elif d0 > 10**24:
        divider = 10**6
    elif d0 > 10**20:
        divider = 10**2
    else:
        divider = 1

    additional_prec: int256 = 0
    if abs(a) > abs(b):
        additional_prec = abs(unsafe_div(a, b))
        a = unsafe_div(unsafe_mul(a, additional_prec), divider)
        b = unsafe_div(b * additional_prec, divider)
        c = unsafe_div(c * additional_prec, divider)
        d = unsafe_div(d * additional_prec, divider)
    else:
        additional_prec = abs(unsafe_div(b, a))
        a = unsafe_div(a // additional_prec, divider)
        b = unsafe_div(unsafe_div(b, additional_prec), divider)
        c = unsafe_div(unsafe_div(c, additional_prec), divider)
        d = unsafe_div(unsafe_div(d, additional_prec), divider)

    # 3*a*c/b - b
    _3ac: int256 = unsafe_mul(3, a) * c
    delta0: int256 = unsafe_div(_3ac, b) - b

    # 9*a*c/b - 2*b - 27*a**2/b*d/b
    delta1: int256 = (
        unsafe_div(3 * _3ac, b)
        - unsafe_mul(2, b)
        - unsafe_div(unsafe_div(27 * a**2, b) * d, b)
    )

    # delta1**2 + 4*delta0**2/b*delta0
    sqrt_arg: int256 = (
        delta1**2 +
        unsafe_div(4 * delta0**2, b) * delta0
    )

    sqrt_val: int256 = 0
    if sqrt_arg > 0:
        sqrt_val = convert(isqrt(convert(sqrt_arg, uint256)), int256)
    else:
        return [self._newton_y(_ANN, _gamma, x, _D, i), 0]

    b_cbrt: int256 = 0
    if b >= 0:
        b_cbrt = convert(self._cbrt(convert(b, uint256)), int256)
    else:
        b_cbrt = -convert(self._cbrt(convert(-b, uint256)), int256)

    second_cbrt: int256 = 0
    if delta1 > 0:
        # convert(self._cbrt(convert((delta1 + sqrt_val), uint256)/2), int256)
        second_cbrt = convert(
            self._cbrt(unsafe_div(convert(delta1 + sqrt_val, uint256), 2)),
            int256
        )
    else:
        second_cbrt = -convert(
            self._cbrt(unsafe_div(convert(-(delta1 - sqrt_val), uint256), 2)),
            int256
        )

    # b_cbrt*b_cbrt/10**18*second_cbrt/10**18
    C1: int256 = unsafe_div(
        unsafe_div(b_cbrt * b_cbrt, 10**18) * second_cbrt,
        10**18
    )

    # (b + b*delta0/C1 - C1)/3
    root_K0: int256 = unsafe_div(b + b * delta0 // C1 - C1, 3)

    # D*D/27/x_k*D/x_j*root_K0/a
    root: int256 = unsafe_div(
        unsafe_div(
            unsafe_div(unsafe_div(D * D, 27), x_k) * D,
            x_j
        ) * root_K0,
        a
    )

    out: uint256[2] = [
        convert(root, uint256),
        convert(unsafe_div(10**18 * root_K0, a), uint256)
    ]

    frac = unsafe_div(out[0] * 10**18, _D)
    assert frac >= 10**16 - 1 and frac < 10**20 + 1,  "Unsafe value for y"
    # due to precision issues, get_y can be off by 2 wei or so wrt _newton_y

    return out


@internal
@view
def _newton_y(
    ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256
) -> uint256:

    # Calculate x[i] given A, gamma, xp and D using newton's method.
    # This is the original method; get_y replaces it, but defaults to
    # this version conditionally.

    # We can ignore safuty checks since they are already done in get_y

    frac: uint256 = 0
    for k: uint256 in range(3):
        if k != i:
            frac = x[k] * 10**18 // D
            assert frac > 10**16 - 1 and frac < 10**20 + 1, "Unsafe values x[i]"

    y: uint256 = D // N_COINS
    K0_i: uint256 = 10**18
    S_i: uint256 = 0

    x_sorted: uint256[N_COINS] = x
    x_sorted[i] = 0
    x_sorted = self._sort(x_sorted)  # From high to low

    convergence_limit: uint256 = max(max(x_sorted[0] // 10**14, D // 10**14), 100)

    for j: uint256 in range(2, N_COINS + 1):
        _x: uint256 = x_sorted[N_COINS - j]
        y = y * D // (_x * N_COINS)  # Small _x first
        S_i += _x

    for j: uint256 in range(N_COINS - 1):
        K0_i = K0_i * x_sorted[j] * N_COINS // D  # Large _x first

    # initialise variables:
    diff: uint256 = 0
    y_prev: uint256 = 0
    K0: uint256 = 0
    S: uint256 = 0
    _g1k0: uint256 = 0
    mul1: uint256 = 0
    mul2: uint256 = 0
    yfprime: uint256 = 0
    _dyfprime: uint256 = 0
    fprime: uint256 = 0
    y_minus: uint256 = 0
    y_plus: uint256 = 0

    for j: uint256 in range(255):
        y_prev = y

        K0 = K0_i * y * N_COINS // D
        S = S_i + y

        _g1k0 = gamma + 10**18
        if _g1k0 > K0:
            _g1k0 = _g1k0 - K0 + 1
        else:
            _g1k0 = K0 - _g1k0 + 1

        # mul1 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN
        mul1 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN

        # 2*K0 // _g1k0
        mul2 = 10**18 + (2 * 10**18) * K0 // _g1k0

        yfprime = 10**18 * y + S * mul2 + mul1
        _dyfprime = D * mul2
        if yfprime < _dyfprime:
            y = y_prev // 2
            continue
        else:
            yfprime -= _dyfprime

        fprime = yfprime // y

        # y -= f // f_prime;  y = (y * fprime - f) // fprime
        y_minus = mul1 // fprime
        y_plus = (yfprime + 10**18 * D) // fprime + y_minus * 10**18 // K0
        y_minus += 10**18 * S // fprime

        if y_plus < y_minus:
            y = y_prev // 2
        else:
            y = y_plus - y_minus

        if y > y_prev:
            diff = y - y_prev
        else:
            diff = y_prev - y

        if diff < max(convergence_limit, y // 10**14):
            frac = y * 10**18 // D
            assert frac > 10**16 - 1 and frac < 10**20 + 1,  "Unsafe value for y"
            return y

    raise "Did not converge"


@external
@view
def newton_D(
    ANN: uint256,
    gamma: uint256,
    x_unsorted: uint256[N_COINS],
    K0_prev: uint256 = 0,
) -> uint256:
    """
    @notice Finding the invariant via newtons method using good initial guesses.
    @dev ANN is higher by the factor A_MULTIPLIER
    @dev ANN is already A * N**N
    @param ANN the A * N**N value
    @param gamma the gamma value
    @param x_unsorted the array of coin balances (not sorted)
    @param K0_prev apriori for newton's method derived from get_y_int. Defaults
           to zero (no apriori)
    """
    x: uint256[N_COINS] = self._sort(x_unsorted)
    assert x[0] < max_value(uint256) // 10**18 * N_COINS**N_COINS  # dev: out of limits
    assert x[0] > 0  # dev: empty pool

    # Safe to do unsafe add since we checked largest x's bounds previously
    S: uint256 = unsafe_add(unsafe_add(x[0], x[1]), x[2])
    D: uint256 = 0

    if K0_prev == 0:
        # Geometric mean of 3 numbers cannot be larger than the largest number
        # so the following is safe to do:
        D = unsafe_mul(N_COINS, self._geometric_mean(x))
    else:
        if S > 10**36:
            D = self._cbrt(
                unsafe_div(
                    unsafe_div(x[0] * x[1], 10**36) * x[2],
                    K0_prev
                ) * 27 * 10**12
            )
        elif S > 10**24:
            D = self._cbrt(
                unsafe_div(
                    unsafe_div(x[0] * x[1], 10**24) * x[2],
                    K0_prev
                ) * 27 * 10**6
            )
        else:
            D = self._cbrt(
                unsafe_div(
                    unsafe_div(x[0] * x[1], 10**18) * x[2],
                    K0_prev
                ) * 27
            )

        # D not zero here if K0_prev > 0, and we checked if x[0] is gt 0.

    # initialise variables:
    K0: uint256 = 0
    _g1k0: uint256 = 0
    mul1: uint256 = 0
    mul2: uint256 = 0
    neg_fprime: uint256 = 0
    D_plus: uint256 = 0
    D_minus: uint256 = 0
    D_prev: uint256 = 0

    diff: uint256 = 0
    frac: uint256 = 0

    for i: uint256 in range(255):

        D_prev = D

        # K0 = 10**18 * x[0] * N_COINS // D * x[1] * N_COINS // D * x[2] * N_COINS // D
        K0 = unsafe_div(
            unsafe_mul(
                unsafe_mul(
                    unsafe_div(
                        unsafe_mul(
                            unsafe_mul(
                                unsafe_div(
                                    unsafe_mul(
                                        unsafe_mul(10**18, x[0]), N_COINS
                                    ),
                                    D,
                                ),
                                x[1],
                            ),
                            N_COINS,
                        ),
                        D,
                    ),
                    x[2],
                ),
                N_COINS,
            ),
            D,
        )  # <-------- We can convert the entire expression using unsafe math.
        #   since x_i is not too far from D, so overflow is not expected. Also
        #      D > 0, since we proved that already. unsafe_div is safe. K0 > 0
        #        since we can safely assume that D < 10**18 * x[0]. K0 is also
        #                            in the range of 10**18 (it's a property).

        _g1k0 = unsafe_add(gamma, 10**18)  # <--------- safe to do unsafe_add.

        if _g1k0 > K0:  #       The following operations can safely be unsafe.
            _g1k0 = unsafe_add(unsafe_sub(_g1k0, K0), 1)
        else:
            _g1k0 = unsafe_add(unsafe_sub(K0, _g1k0), 1)

        # D // (A * N**N) * _g1k0**2 // gamma**2
        # mul1 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN
        mul1 = unsafe_div(
            unsafe_mul(
                unsafe_mul(
                    unsafe_div(
                        unsafe_mul(
                            unsafe_div(unsafe_mul(10**18, D), gamma), _g1k0
                        ),
                        gamma,
                    ),
                    _g1k0,
                ),
                A_MULTIPLIER,
            ),
            ANN,
        )  # <------ Since D > 0, gamma is small, _g1k0 is small, the rest are
        #        non-zero and small constants, and D has a cap in this method,
        #                    we can safely convert everything to unsafe maths.

        # 2*N*K0 // _g1k0
        # mul2 = (2 * 10**18) * N_COINS * K0 // _g1k0
        mul2 = unsafe_div(
            unsafe_mul(2 * 10**18 * N_COINS, K0), _g1k0
        )  # <--------------- K0 is approximately around D, which has a cap of
        #      10**15 * 10**18 + 1, since we get that in get_y which is called
        #    with newton_D. _g1k0 > 0, so the entire expression can be unsafe.

        # neg_fprime: uint256 = (S + S * mul2 // 10**18) + mul1 * N_COINS // K0 - mul2 * D // 10**18
        neg_fprime = unsafe_sub(
            unsafe_add(
                unsafe_add(S, unsafe_div(unsafe_mul(S, mul2), 10**18)),
                unsafe_div(unsafe_mul(mul1, N_COINS), K0),
            ),
            unsafe_div(unsafe_mul(mul2, D), 10**18),
        )  # <--- mul1 is a big number but not huge: safe to unsafely multiply
        # with N_coins. neg_fprime > 0 if this expression executes.
        # mul2 is in the range of 10**18, since K0 is in that range, S * mul2
        # is safe. The first three sums can be done using unsafe math safely
        # and since the final expression will be small since mul2 is small, we
        # can safely do the entire expression unsafely.

        # D -= f // fprime
        # D * (neg_fprime + S) // neg_fprime
        D_plus = unsafe_div(D * unsafe_add(neg_fprime, S), neg_fprime)

        # D*D // neg_fprime
        D_minus = unsafe_div(D * D, neg_fprime)

        # Since we know K0 > 0, and neg_fprime > 0, several unsafe operations
        # are possible in the following. Also, (10**18 - K0) is safe to mul.
        # So the only expressions we keep safe are (D_minus + ...) and (D * ...)
        if 10**18 > K0:
            # D_minus += D * (mul1 // neg_fprime) // 10**18 * (10**18 - K0) // K0
            D_minus += unsafe_div(
                unsafe_mul(
                    unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18),
                    unsafe_sub(10**18, K0),
                ),
                K0,
            )
        else:
            # D_minus -= D * (mul1 // neg_fprime) // 10**18 * (K0 - 10**18) // K0
            D_minus -= unsafe_div(
                unsafe_mul(
                    unsafe_div(D * unsafe_div(mul1, neg_fprime), 10**18),
                    unsafe_sub(K0, 10**18),
                ),
                K0,
            )

        if D_plus > D_minus:
            D = unsafe_sub(D_plus, D_minus)  # <--------- Safe since we check.
        else:
            D = unsafe_div(unsafe_sub(D_minus, D_plus), 2)

        if D > D_prev:
            diff = unsafe_sub(D, D_prev)
        else:
            diff = unsafe_sub(D_prev, D)

        # Could reduce precision for gas efficiency here:
        if unsafe_mul(diff, 10**14) < max(10**16, D):

            # Test that we are safe with the next get_y
            for _x: uint256 in x:
                frac = unsafe_div(unsafe_mul(_x, 10**18), D)
                assert frac >= 10**16 - 1 and frac < 10**20 + 1, "Unsafe values x[i]"

            return D
    raise "Did not converge"


@external
@view
def get_p(
    _xp: uint256[N_COINS], _D: uint256, _A_gamma: uint256[N_COINS-1]
) -> uint256[N_COINS-1]:
    """
    @notice Calculates dx/dy.
    @dev Output needs to be multiplied with price_scale to get the actual value.
    @param _xp Balances of the pool.
    @param _D Current value of D.
    @param _A_gamma Amplification coefficient and gamma.
    """

    assert _D > 10**17 - 1 and _D < 10**15 * 10**18 + 1  # dev: unsafe D values

    # K0 = P * N**N // D**N.
    # K0 is dimensionless and has 10**36 precision:
    K0: uint256 = unsafe_div(
        unsafe_div(unsafe_div(27 * _xp[0] * _xp[1], _D) * _xp[2], _D) * 10**36,
        _D
    )

    # GK0 is in 10**36 precision and is dimensionless.
    # GK0 = (
    #     2 * _K0 * _K0 // 10**36 * _K0 // 10**36
    #     + (gamma + 10**18)**2
    #     - (_K0 * _K0 // 10**36 * (2 * gamma + 3 * 10**18) // 10**18)
    # )
    # GK0 is always positive. So the following should never revert:
    GK0: uint256 = (
        unsafe_div(unsafe_div(2 * K0 * K0, 10**36) * K0, 10**36)
        + pow_mod256(unsafe_add(_A_gamma[1], 10**18), 2)
        - unsafe_div(
            unsafe_div(pow_mod256(K0, 2), 10**36) * unsafe_add(unsafe_mul(2, _A_gamma[1]), 3 * 10**18),
            10**18
        )
    )

    # NNAG2 = N**N * A * gamma**2
    NNAG2: uint256 = unsafe_div(unsafe_mul(_A_gamma[0], pow_mod256(_A_gamma[1], 2)), A_MULTIPLIER)

    # denominator = (GK0 + NNAG2 * x // D * _K0 // 10**36)
    denominator: uint256 = (GK0 + unsafe_div(unsafe_div(NNAG2 * _xp[0], _D) * K0, 10**36) )

    # p_xy = x * (GK0 + NNAG2 * y // D * K0 // 10**36) // y * 10**18 // denominator
    # p_xz = x * (GK0 + NNAG2 * z // D * K0 // 10**36) // z * 10**18 // denominator
    # p is in 10**18 precision.
    return [
        unsafe_div(
            _xp[0] * ( GK0 + unsafe_div(unsafe_div(NNAG2 * _xp[1], _D) * K0, 10**36) ) // _xp[1] * 10**18,
            denominator
        ),
        unsafe_div(
            _xp[0] * ( GK0 + unsafe_div(unsafe_div(NNAG2 * _xp[2], _D) * K0, 10**36) ) // _xp[2] * 10**18,
            denominator
        ),
    ]


# --------------------------- Math Utils -------------------------------------


@external
@view
def cbrt(x: uint256) -> uint256:
    """
    @notice Calculate the cubic root of a number in 1e18 precision
    @dev Consumes around 1500 gas units
    @param x The number to calculate the cubic root of
    """
    return self._cbrt(x)


@external
@view
def geometric_mean(_x: uint256[3]) -> uint256:
    """
    @notice Calculate the geometric mean of a list of numbers in 1e18 precision.
    @param _x list of 3 numbers to sort
    """
    return self._geometric_mean(_x)


@external
@view
def reduction_coefficient(x: uint256[N_COINS], fee_gamma: uint256) -> uint256:
    """
    @notice Calculates the reduction coefficient for the given x and fee_gamma
    @dev This method is used for calculating fees.
    @param x The x values
    @param fee_gamma The fee gamma value
    """
    return self._reduction_coefficient(x, fee_gamma)


@external
@view
def wad_exp(_power: int256) -> uint256:
    """
    @notice Calculates the e**x with 1e18 precision
    @param _power The number to calculate the exponential of
    """
    return self._snekmate_wad_exp(_power)


@internal
@pure
def _reduction_coefficient(x: uint256[N_COINS], fee_gamma: uint256) -> uint256:

    # fee_gamma // (fee_gamma + (1 - K))
    # where
    # K = prod(x) // (sum(x) // N)**N
    # (all normalized to 1e18)

    S: uint256 = x[0] + x[1] + x[2]

    # Could be good to pre-sort x, but it is used only for dynamic fee
    K: uint256 = 10**18 * N_COINS * x[0] // S
    K = unsafe_div(K * N_COINS * x[1], S)  # <- unsafe div is safu.
    K = unsafe_div(K * N_COINS * x[2], S)

    if fee_gamma > 0:
        K = fee_gamma * 10**18 // (fee_gamma + 10**18 - K)

    return K


@internal
@pure
def _snekmate_wad_exp(x: int256) -> uint256:

    """
    @dev Calculates the natural exponential function of a signed integer with
         a precision of 1e18.
    @notice Note that this function consumes about 810 gas units. The implementation
            is inspired by Remco Bloemen's implementation under the MIT license here:
            https://xn--2-umb.com/22/exp-ln.
    @dev This implementation is derived from Snekmate, which is authored
         by pcaversaccio (Snekmate), distributed under the AGPL-3.0 license.
         https://github.com/pcaversaccio/snekmate
    @param x The 32-byte variable.
    @return int256 The 32-byte calculation result.
    """
    value: int256 = x

    # If the result is `< 0.5`, we return zero. This happens when we have the following:
    # "x <= floor(log(0.5e18) * 1e18) ~ -42e18".
    if (x <= -42139678854452767551):
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


@internal
@pure
def _snekmate_log_2(x: uint256, roundup: bool) -> uint256:
    """
    @notice An `internal` helper function that returns the log in base 2
         of `x`, following the selected rounding direction.
    @dev This implementation is derived from Snekmate, which is authored
         by pcaversaccio (Snekmate), distributed under the AGPL-3.0 license.
         https://github.com/pcaversaccio/snekmate
    @dev Note that it returns 0 if given 0. The implementation is
         inspired by OpenZeppelin's implementation here:
         https://github.com/OpenZeppelin/openzeppelin-contracts/blob/master/contracts/utils/math/Math.sol.
    @param x The 32-byte variable.
    @param roundup The Boolean variable that specifies whether
           to round up or not. The default `False` is round down.
    @return uint256 The 32-byte calculation result.
    """
    value: uint256 = x
    result: uint256 = empty(uint256)

    # The following lines cannot overflow because we have the well-known
    # decay behaviour of `log_2(max_value(uint256)) < max_value(uint256)`.
    if x >> 128 != empty(uint256):
        value = x >> 128
        result = 128
    if value >> 64 != empty(uint256):
        value = value >> 64
        result = unsafe_add(result, 64)
    if value >> 32 != empty(uint256):
        value = value >> 32
        result = unsafe_add(result, 32)
    if value >> 16 != empty(uint256):
        value = value >> 16
        result = unsafe_add(result, 16)
    if value >> 8 != empty(uint256):
        value = value >> 8
        result = unsafe_add(result, 8)
    if value >> 4 != empty(uint256):
        value = value >> 4
        result = unsafe_add(result, 4)
    if value >> 2 != empty(uint256):
        value = value >> 2
        result = unsafe_add(result, 2)
    if value >> 1 != empty(uint256):
        result = unsafe_add(result, 1)

    if (roundup and (1 << result) < x):
        result = unsafe_add(result, 1)

    return result


@internal
@pure
def _cbrt(x: uint256) -> uint256:

    xx: uint256 = 0
    if x >= 115792089237316195423570985008687907853269 * 10**18:
        xx = x
    elif x >= 115792089237316195423570985008687907853269:
        xx = unsafe_mul(x, 10**18)
    else:
        xx = unsafe_mul(x, 10**36)

    log2x: int256 = convert(self._snekmate_log_2(xx, False), int256)

    # When we divide log2x by 3, the remainder is (log2x % 3).
    # So if we just multiply 2**(log2x/3) and discard the remainder to calculate our
    # guess, the newton method will need more iterations to converge to a solution,
    # since it is missing that precision. It's a few more calculations now to do less
    # calculations later:
    # pow = log2(x) // 3
    # remainder = log2(x) % 3
    # initial_guess = 2 ** pow * cbrt(2) ** remainder
    # substituting -> 2 = 1.26 ≈ 1260 // 1000, we get:
    #
    # initial_guess = 2 ** pow * 1260 ** remainder // 1000 ** remainder

    remainder: uint256 = convert(log2x, uint256) % 3
    a: uint256 = unsafe_div(
        unsafe_mul(
            pow_mod256(2, unsafe_div(convert(log2x, uint256), 3)),  # <- pow
            pow_mod256(1260, remainder),
        ),
        pow_mod256(1000, remainder),
    )

    # Because we chose good initial values for cube roots, 7 newton raphson iterations
    # are just about sufficient. 6 iterations would result in non-convergences, and 8
    # would be one too many iterations. Without initial values, the iteration count
    # can go up to 20 or greater. The iterations are unrolled. This reduces gas costs
    # but takes up more bytecode:
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)
    a = unsafe_div(unsafe_add(unsafe_mul(2, a), unsafe_div(xx, unsafe_mul(a, a))), 3)

    if x >= 115792089237316195423570985008687907853269 * 10**18:
        a = unsafe_mul(a, 10**12)
    elif x >= 115792089237316195423570985008687907853269:
        a = unsafe_mul(a, 10**6)

    return a


@internal
@pure
def _sort(unsorted_x: uint256[3]) -> uint256[3]:

    # Sorts a three-array number in a descending order:

    x: uint256[N_COINS] = unsorted_x
    temp_var: uint256 = x[0]
    if x[0] < x[1]:
        x[0] = x[1]
        x[1] = temp_var
    if x[0] < x[2]:
        temp_var = x[0]
        x[0] = x[2]
        x[2] = temp_var
    if x[1] < x[2]:
        temp_var = x[1]
        x[1] = x[2]
        x[2] = temp_var

    return x


@internal
@view
def _geometric_mean(_x: uint256[3]) -> uint256:

    # calculates a geometric mean for three numbers.

    prod: uint256 = unsafe_div(
        unsafe_div(_x[0] * _x[1], 10**18) * _x[2],
        10**18
    )

    if prod == 0:
        return 0

    return self._cbrt(prod)
