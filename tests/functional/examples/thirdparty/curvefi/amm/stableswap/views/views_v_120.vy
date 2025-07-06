# pragma version >=0.4.2
# pragma evm-version paris
"""
@title CurveStableSwapNGViews
@custom:version 1.2.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice Auxiliary contract for Stableswap-NG containing utility methods for
        integrators
"""

version: public(constant(String[8])) = "1.2.0"

from ethereum.ercs import IERC20Detailed

interface StableSwapNG:
    def N_COINS() -> uint256: view
    def BASE_POOL() -> address: view
    def BASE_N_COINS() -> uint256: view
    def stored_rates() -> DynArray[uint256, MAX_COINS]: view
    def balances(i: uint256) -> uint256: view
    def get_balances() -> DynArray[uint256, MAX_COINS]: view
    def fee() -> uint256: view
    def get_dy(i: int128, j: int128, dx: uint256) -> uint256: view
    def A() -> uint256: view
    def calc_withdraw_one_coin(_token_amount: uint256, i: int128) -> uint256: view
    def totalSupply() -> uint256: view
    def offpeg_fee_multiplier() -> uint256: view
    def coins(i: uint256) -> address: view

A_PRECISION: constant(uint256) = 100
MAX_COINS: constant(uint256) = 8
PRECISION: constant(uint256) = 10 ** 18
FEE_DENOMINATOR: constant(uint256) = 10 ** 10


VERSION: public(constant(String[8])) = "1.2.0"
# first version was: 0xe0B15824862f3222fdFeD99FeBD0f7e0EC26E1FA (ethereum mainnet)
# second version was: 0x13526206545e2DC7CcfBaF28dC88F440ce7AD3e0 (ethereum mainnet)


# ------------------------------ Public Getters ------------------------------


@view
@external
def get_dx(i: int128, j: int128, dy: uint256, pool: address) -> uint256:
    """
    @notice Calculate the current input dx given output dy
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param dy Amount of `j` being received after exchange
    @return Amount of `i` predicted
    """
    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()
    return self._get_dx(i, j, dy, pool, False, N_COINS)


@view
@external
def get_dy(i: int128, j: int128, dx: uint256, pool: address) -> uint256:
    """
    @notice Calculate the current output dy given input dx
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param dx Amount of `i` being exchanged
    @return Amount of `j` predicted
    """
    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    rates, balances, xp = self._get_rates_balances_xp(pool, N_COINS)

    amp: uint256 = staticcall StableSwapNG(pool).A() * A_PRECISION
    D: uint256 = self.get_D(xp, amp, N_COINS)

    x: uint256 = xp[i] + (dx * rates[i] // PRECISION)
    y: uint256 = self.get_y(i, j, x, xp, amp, D, N_COINS)
    dy: uint256 = xp[j] - y - 1

    base_fee: uint256 = staticcall StableSwapNG(pool).fee()
    fee_multiplier: uint256 = staticcall StableSwapNG(pool).offpeg_fee_multiplier()
    fee: uint256 = self._dynamic_fee((xp[i] + x) // 2, (xp[j] + y) // 2, base_fee, fee_multiplier) * dy // FEE_DENOMINATOR

    return (dy - fee) * PRECISION // rates[j]


@view
@external
def get_dx_underlying(
    i: int128,
    j: int128,
    dy: uint256,
    pool: address,
) -> uint256:

    BASE_POOL: address = staticcall StableSwapNG(pool).BASE_POOL()
    BASE_N_COINS: uint256 = staticcall StableSwapNG(pool).BASE_N_COINS()
    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()
    base_pool_has_static_fee: bool = self._has_static_fee(BASE_POOL)
    base_pool_lp_token: address = staticcall StableSwapNG(pool).coins(1)

    # CASE 1: Swap does not involve Metapool at all. In this case, we kindly ask the user
    # to use the right pool for their swaps.
    if min(i, j) > 0:
        raise "Not a Metapool Swap. Use Base pool."

    # CASE 2:
    #    1. meta token_0 of (unknown amount) > base pool lp_token
    #    2. base pool lp_token > calc_withdraw_one_coin gives dy amount of (j-1)th base coin
    # So, need to do the following calculations:
    #    1. calc_token_amounts on base pool for depositing liquidity on (j-1)th token > lp_tokens.
    #    2. get_dx on metapool for i = 0, and j = 1 (base lp token) with amt calculated in (1).
    if i == 0:
        # Calculate LP tokens that are burnt to receive dy amount of base_j tokens.
        lp_amount_burnt: uint256 = self._base_calc_token_amount(
            dy, j - 1, BASE_N_COINS, BASE_POOL, base_pool_lp_token, False,
        )
        return self._get_dx(0, 1, lp_amount_burnt, pool, False, N_COINS)

    # CASE 3: Swap in token i-1 from base pool and swap out dy amount of token 0 (j) from metapool.
    #    1. deposit i-1 token from base pool > receive base pool lp_token
    #    2. swap base pool lp token > 0th token of the metapool
    # So, need to do the following calculations:
    #    1. get_dx on metapool with i = 0, j = 1 > gives how many base lp tokens are required for receiving
    #       dy amounts of i-1 tokens from the metapool
    #    2. We have number of lp tokens: how many i-1 base pool coins are needed to mint that many tokens?
    #       We don't have a method where user inputs lp tokens and it gives number of coins of (i-1)th token
    #       is needed to mint that many base_lp_tokens. Instead, we will use calc_withdraw_one_coin. That's
    #       close enough.
    lp_amount_required: uint256 = self._get_dx(1, 0, dy, pool, False, N_COINS)
    return staticcall StableSwapNG(BASE_POOL).calc_withdraw_one_coin(lp_amount_required, i-1)


@view
@external
def get_dy_underlying(
    i: int128,
    j: int128,
    dx: uint256,
    pool: address,
) -> uint256:
    """
    @notice Calculate the current output dy given input dx on underlying
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param dx Amount of `i` being exchanged
    @return Amount of `j` predicted
    """

    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()
    MAX_COIN: int128 = convert(N_COINS, int128) - 1
    BASE_POOL: address = staticcall StableSwapNG(pool).BASE_POOL()
    base_lp_token: address = staticcall StableSwapNG(pool).coins(1)

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    rates, balances, xp = self._get_rates_balances_xp(pool, N_COINS)

    x: uint256 = 0
    base_i: int128 = 0
    base_j: int128 = 0
    meta_i: int128 = 0
    meta_j: int128 = 0

    if i != 0:
        base_i = i - MAX_COIN
        meta_i = 1
    if j != 0:
        base_j = j - MAX_COIN
        meta_j = 1

    if i == 0:

        x = xp[i] + dx * rates[0] // 10**18

    else:

        if j == 0:

            # i is from BasePool
            base_n_coins: uint256 = staticcall StableSwapNG(pool).BASE_N_COINS()
            x = self._base_calc_token_amount(
                dx,
                base_i,
                base_n_coins,
                BASE_POOL,
                base_lp_token,
                True,
            ) * rates[1] // PRECISION

            # Adding number of pool tokens
            x += xp[1]

        else:
            # If both are from the base pool
            return staticcall StableSwapNG(BASE_POOL).get_dy(base_i, base_j, dx)

    # This pool is involved only when in-pool assets are used
    amp: uint256 = staticcall StableSwapNG(pool).A() * A_PRECISION
    D: uint256 = self.get_D(xp, amp, N_COINS)
    y: uint256 = self.get_y(meta_i, meta_j, x, xp, amp, D, N_COINS)
    dy: uint256 = xp[meta_j] - y - 1

    # calculate output after subtracting dynamic fee
    base_fee: uint256 = staticcall StableSwapNG(pool).fee()
    fee_multiplier: uint256 = staticcall StableSwapNG(pool).offpeg_fee_multiplier()

    dynamic_fee: uint256 = self._dynamic_fee((xp[meta_i] + x) // 2, (xp[meta_j] + y) // 2, base_fee, fee_multiplier)
    dy = (dy - dynamic_fee * dy // FEE_DENOMINATOR)

    # If output is going via the metapool
    if j == 0:
        dy = dy * 10**18 // rates[0]
    else:
        # j is from BasePool
        # The fee is already accounted for
        dy = staticcall StableSwapNG(BASE_POOL).calc_withdraw_one_coin(dy * PRECISION // rates[1], base_j)

    return dy


@view
@external
def calc_token_amount(
    _amounts: DynArray[uint256, MAX_COINS],
    _is_deposit: bool,
    pool: address
) -> uint256:
    """
    @notice Calculate addition or reduction in token supply from a deposit or withdrawal
    @dev Only works for StableswapNG pools and not legacy versions
    @param _amounts Amount of each coin being deposited
    @param _is_deposit set True for deposits, False for withdrawals
    @return Expected amount of LP tokens received
    """

    return self._calc_token_amount(
        _amounts,
        _is_deposit,
        pool,
        pool,
        staticcall StableSwapNG(pool).N_COINS()
    )


@view
@external
def calc_withdraw_one_coin(_burn_amount: uint256, i: int128, pool: address) -> uint256:
    # First, need to calculate
    # * Get current D
    # * Solve Eqn against y_i for D - _token_amount

    amp: uint256 = staticcall StableSwapNG(pool).A() * A_PRECISION
    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    rates, balances, xp = self._get_rates_balances_xp(pool, N_COINS)

    D0: uint256 = self.get_D(xp, amp, N_COINS)

    total_supply: uint256 = staticcall StableSwapNG(pool).totalSupply()
    D1: uint256 = D0 - _burn_amount * D0 // total_supply
    new_y: uint256 = self.get_y_D(amp, i, xp, D1, N_COINS)
    ys: uint256 = (D0 + D1) // (2 * N_COINS)

    base_fee: uint256 = staticcall StableSwapNG(pool).fee() * N_COINS // (4 * (N_COINS - 1))
    fee_multiplier: uint256 = staticcall StableSwapNG(pool).offpeg_fee_multiplier()
    xp_reduced: DynArray[uint256, MAX_COINS] = xp
    xp_j: uint256 = 0
    xavg: uint256 = 0
    dynamic_fee: uint256 = 0

    for j: uint256 in range(MAX_COINS):

        if j == N_COINS:
            break

        dx_expected: uint256 = 0
        xp_j = xp[j]
        if convert(j, int128) == i:
            dx_expected = xp_j * D1 // D0 - new_y
            xavg = (xp[j] + new_y) // 2
        else:
            dx_expected = xp_j - xp_j * D1 // D0
            xavg = xp[j]

        dynamic_fee = self._dynamic_fee(xavg, ys, base_fee, fee_multiplier)
        xp_reduced[j] = xp_j - dynamic_fee * dx_expected // FEE_DENOMINATOR

    dy: uint256 = xp_reduced[i] - self.get_y_D(amp, i, xp_reduced, D1, N_COINS)
    dy = (dy - 1) * PRECISION // rates[i]  # Withdraw less to account for rounding errors

    return dy


@view
@external
def dynamic_fee(i: int128, j: int128, pool:address) -> uint256:
    """
    @notice Return the fee for swapping between `i` and `j`
    @param i Index value for the coin to send
    @param j Index value of the coin to recieve
    @return Swap fee expressed as an integer with 1e10 precision
    """
    N_COINS: uint256 = staticcall StableSwapNG(pool).N_COINS()
    fee: uint256 = staticcall StableSwapNG(pool).fee()
    fee_multiplier: uint256 = staticcall StableSwapNG(pool).offpeg_fee_multiplier()

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    rates, balances, xp = self._get_rates_balances_xp(pool, N_COINS)

    return self._dynamic_fee(xp[i], xp[j], fee, fee_multiplier)


# ----------------------------- Utility Methods ------------------------------


@view
@internal
def _has_static_fee(pool: address) -> bool:

    success: bool = False
    response: Bytes[32] = b""
    success, response = raw_call(
        pool,
        concat(
            method_id("dynamic_fee(int128,int128)"),
            convert(1, bytes32),
            convert(0, bytes32)
        ),
        max_outsize=32,
        revert_on_failure=False,
        is_static_call=True
    )

    return success


@view
@internal
def _get_dx(
    i: int128,
    j: int128,
    dy: uint256,
    pool: address,
    static_fee: bool,
    N_COINS: uint256
) -> uint256:

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    rates, balances, xp = self._get_rates_balances_xp(pool, N_COINS)

    amp: uint256 = staticcall StableSwapNG(pool).A() * A_PRECISION
    D: uint256 = self.get_D(xp, amp, N_COINS)

    base_fee: uint256 = staticcall StableSwapNG(pool).fee()
    dy_with_fee: uint256 = dy * rates[j] // PRECISION + 1

    fee: uint256 = base_fee
    if not static_fee:
        fee_multiplier: uint256 = staticcall StableSwapNG(pool).offpeg_fee_multiplier()
        fee = self._dynamic_fee(xp[i], xp[j], base_fee, fee_multiplier)

    y: uint256 = xp[j] - dy_with_fee * FEE_DENOMINATOR // (FEE_DENOMINATOR - fee)
    x: uint256 = self.get_y(j, i, y, xp, amp, D, N_COINS)
    return (x - xp[i]) * PRECISION // rates[i]


@view
@internal
def _dynamic_fee(xpi: uint256, xpj: uint256, _fee: uint256, _fee_multiplier: uint256) -> uint256:

    if _fee_multiplier <= FEE_DENOMINATOR:
        return _fee

    xps2: uint256 = (xpi + xpj) ** 2
    return (
        (_fee_multiplier * _fee) //
        ((_fee_multiplier - FEE_DENOMINATOR) * 4 * xpi * xpj // xps2 + FEE_DENOMINATOR)
    )


@internal
@view
def _calc_token_amount(
    _amounts: DynArray[uint256, MAX_COINS],
    _is_deposit: bool,
    pool: address,
    pool_lp_token: address,
    n_coins: uint256,
) -> uint256:

    amp: uint256 = staticcall StableSwapNG(pool).A() * A_PRECISION

    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    old_balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    pool_is_ng: bool = raw_call(
        pool,
        method_id("D_ma_time()"),
        revert_on_failure=False,
        is_static_call=True
    )
    use_dynamic_fees: bool = True
    if pool_is_ng:
        rates, old_balances, xp = self._get_rates_balances_xp(pool, n_coins)
    else:
        use_dynamic_fees = False
        for i: uint256 in range(n_coins, bound=MAX_COINS):
            rates.append(
                10 ** (36 - convert(staticcall IERC20Detailed(staticcall StableSwapNG(pool).coins(i)).decimals(), uint256))
            )
            old_balances.append(staticcall StableSwapNG(pool).balances(i))
            xp.append(rates[i] * old_balances[i] // PRECISION)

    # Initial invariant
    D0: uint256 = self.get_D(xp, amp, n_coins)

    total_supply: uint256 = staticcall StableSwapNG(pool_lp_token).totalSupply()
    new_balances: DynArray[uint256, MAX_COINS] = old_balances
    for i: uint256 in range(n_coins, bound=MAX_COINS):
        amount: uint256 = _amounts[i]
        if _is_deposit:
            new_balances[i] += amount
        else:
            new_balances[i] -= amount

    # Invariant after change
    for idx: uint256 in range(n_coins, bound=MAX_COINS):
        xp[idx] = rates[idx] * new_balances[idx] // PRECISION
    D1: uint256 = self.get_D(xp, amp, n_coins)

    # We need to recalculate the invariant accounting for fees
    # to calculate fair user's share
    D2: uint256 = D1
    fee_multiplier: uint256 = 0
    _dynamic_fee_i: uint256 = 0
    if total_supply > 0:

        # Only account for fees if we are not the first to deposit
        base_fee: uint256 = staticcall StableSwapNG(pool).fee() * n_coins // (4 * (n_coins - 1))
        if use_dynamic_fees:
            fee_multiplier = staticcall StableSwapNG(pool).offpeg_fee_multiplier()

        xs: uint256 = 0
        ys: uint256 = (D0 + D1) // n_coins

        for i: uint256 in range(n_coins, bound=MAX_COINS):

            ideal_balance: uint256 = D1 * old_balances[i] // D0
            difference: uint256 = 0
            new_balance: uint256 = new_balances[i]
            if ideal_balance > new_balance:
                difference = ideal_balance - new_balance
            else:
                difference = new_balance - ideal_balance

            xs = rates[i] * (old_balances[i] + new_balance) // PRECISION

            # use dynamic fees only if pool is NG
            if use_dynamic_fees:
                _dynamic_fee_i = self._dynamic_fee(xs, ys, base_fee, fee_multiplier)
                new_balances[i] -= _dynamic_fee_i * difference // FEE_DENOMINATOR
            else:
                new_balances[i] -= base_fee * difference // FEE_DENOMINATOR

        for idx: uint256 in range(n_coins, bound=MAX_COINS):
            xp[idx] = rates[idx] * new_balances[idx] // PRECISION

        D2 = self.get_D(xp, amp, n_coins)
    else:
        return D1  # Take the dust if there was any

    diff: uint256 = 0
    if _is_deposit:
        diff = D2 - D0
    else:
        diff = D0 - D2
    return diff * total_supply // D0


@internal
@view
def _base_calc_token_amount(
    dx: uint256,
    base_i: int128,
    base_n_coins: uint256,
    base_pool: address,
    base_pool_lp_token: address,
    is_deposit: bool,
) -> uint256:

    base_inputs: DynArray[uint256, MAX_COINS] = [0, 0, 0, 0, 0, 0, 0, 0]
    base_inputs[base_i] = dx

    return self._calc_token_amount(
        base_inputs,
        is_deposit,
        base_pool,
        base_pool_lp_token,
        base_n_coins
    )


@internal
@pure
def newton_y(b: uint256, c: uint256, D: uint256, _y: uint256) -> uint256:

    y_prev: uint256 = 0
    y: uint256 = _y

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


@view
@internal
def get_y(
    i: int128,
    j: int128,
    x: uint256,
    xp: DynArray[uint256, MAX_COINS],
    _amp: uint256,
    _D: uint256,
    N_COINS: uint256
) -> uint256:
    """
    Calculate x[j] if one makes x[i] = x

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price//precision

    assert i != j       # dev: same coin
    assert j >= 0       # dev: j below zero
    assert j < convert(N_COINS, int128)  # dev: j above N_COINS

    # should be unreachable, but good for safety
    assert i >= 0
    assert i < convert(N_COINS, int128)

    amp: uint256 = _amp
    D: uint256 = _D
    S_: uint256 = 0
    _x: uint256 = 0
    c: uint256 = D
    Ann: uint256 = amp * N_COINS

    for _i: uint256 in range(MAX_COINS):

        if _i == N_COINS:
            break

        if  convert(_i, int128) == i:
            _x = x
        elif convert(_i, int128) != j:
            _x = xp[_i]
        else:
            continue
        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_PRECISION // (Ann * N_COINS)
    b: uint256 = S_ + D * A_PRECISION // Ann  # - D
    y: uint256 = D

    return self.newton_y(b, c, D, y)


@pure
@internal
def get_D(_xp: DynArray[uint256, MAX_COINS], _amp: uint256, N_COINS: uint256) -> uint256:
    """
    D invariant calculation in non-overflowing integer operations
    iteratively

    A * sum(x_i) * n**n + D = A * D * n**n + D**(n+1) // (n**n * prod(x_i))

    Converging solution:
    D[j+1] = (A * n**n * sum(x_i) - D[j]**(n+1) // (n**n prod(x_i))) // (A * n**n - 1)
    """
    S: uint256 = 0
    for i: uint256 in range(MAX_COINS):
        if i == N_COINS:
            break
        S += _xp[i]

    if S == 0:
        return 0

    D: uint256 = S
    Ann: uint256 = _amp * N_COINS

    for i: uint256 in range(255):

        D_P: uint256 = D
        for x: uint256 in _xp:
            D_P = D_P * D // x
        D_P //= pow_mod256(N_COINS, N_COINS)
        Dprev: uint256 = D

        D = (Ann * S // A_PRECISION + D_P * N_COINS) * D // ((Ann - A_PRECISION) * D // A_PRECISION + (N_COINS + 1) * D_P)
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


@pure
@internal
def get_y_D(
    A: uint256,
    i: int128,
    xp: DynArray[uint256, MAX_COINS],
    D: uint256,
    N_COINS: uint256
) -> uint256:
    """
    Calculate x[i] if one reduces D from being calculated for xp to D

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price//precision

    N_COINS_128: int128 = convert(N_COINS, int128)
    assert i >= 0  # dev: i below zero
    assert i < N_COINS_128  # dev: i above N_COINS

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = A * N_COINS

    for _i: uint256 in range(MAX_COINS):

        if _i == N_COINS:
            break

        if _i != convert(i, uint256):
            _x = xp[_i]
        else:
            continue
        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_PRECISION // (Ann * N_COINS)
    b: uint256 = S_ + D * A_PRECISION // Ann
    y: uint256 = D

    return self.newton_y(b, c, D, y)


@view
@internal
def _get_rates_balances_xp(pool: address, N_COINS: uint256) -> (
    DynArray[uint256, MAX_COINS],
    DynArray[uint256, MAX_COINS],
    DynArray[uint256, MAX_COINS],
):

    rates: DynArray[uint256, MAX_COINS] = staticcall StableSwapNG(pool).stored_rates()
    balances: DynArray[uint256, MAX_COINS] = staticcall StableSwapNG(pool).get_balances()
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for idx: uint256 in range(MAX_COINS):
        if idx == N_COINS:
            break
        xp.append(rates[idx] * balances[idx] // PRECISION)

    return rates, balances, xp
