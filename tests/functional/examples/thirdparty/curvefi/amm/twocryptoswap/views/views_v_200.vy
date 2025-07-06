# pragma version >=0.4.2
# pragma optimize gas
# pragma evm-version paris

"""
@title CurveTwocryptoViews
@custom:version 2.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice This contract contains view-only external methods which can be
        gas-inefficient when called from smart contracts.
"""

from ethereum.ercs import IERC20

# ------------------------------- Version ------------------------------------

version: public(constant(String[8])) = "2.0.0"

# --------------------------------- Interfaces -------------------------------

interface Curve:
    def MATH() -> Math: view
    def A() -> uint256: view
    def gamma() -> uint256: view
    def price_scale() -> uint256: view
    def price_oracle() -> uint256: view
    def get_virtual_price() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def D() -> uint256: view
    def fee_calc(xp: uint256[N_COINS]) -> uint256: view
    def calc_token_fee(
        amounts: uint256[N_COINS], xp: uint256[N_COINS]
    ) -> uint256: view
    def future_A_gamma_time() -> uint256: view
    def totalSupply() -> uint256: view
    def precisions() -> uint256[N_COINS]: view
    def packed_fee_params() -> uint256: view


interface Math:
    def newton_D(
        ANN: uint256,
        gamma: uint256,
        x_unsorted: uint256[N_COINS],
        K0_prev: uint256
    ) -> uint256: view
    def get_y(
        ANN: uint256,
        gamma: uint256,
        x: uint256[N_COINS],
        D: uint256,
        i: uint256,
    ) -> uint256[2]: view
    def newton_y(
        ANN: uint256,
        gamma: uint256,
        x: uint256[N_COINS],
        D: uint256,
        i: uint256,
    ) -> uint256: view


N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10**18


@external
@view
def get_dy(
    i: uint256, j: uint256, dx: uint256, swap: address
) -> uint256:

    dy: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])

    # dy = (get_y(x + dx) - y) * (1 - fee)
    dy, xp = self._get_dy_nofee(i, j, dx, swap)
    dy -= Curve(swap).fee_calc(xp) * dy // 10**10

    return dy


@view
@external
def get_dx(
    i: uint256, j: uint256, dy: uint256, swap: address
) -> uint256:

    dx: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    fee_dy: uint256 = 0
    _dy: uint256 = dy

    # for more precise dx (but never exact), increase num loops
    for k: uint256 in range(5):
        dx, xp = self._get_dx_fee(i, j, _dy, swap)
        fee_dy = Curve(swap).fee_calc(xp) * _dy // 10**10
        _dy = dy + fee_dy + 1

    return dx


@view
@external
def calc_withdraw_one_coin(
    token_amount: uint256, i: uint256, swap: address
) -> uint256:

    return self._calc_withdraw_one_coin(token_amount, i, swap)[0]


@view
@external
def calc_token_amount(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> uint256:

    d_token: uint256 = 0
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    xp: uint256[N_COINS] = empty(uint256[N_COINS])

    d_token, amountsp, xp = self._calc_dtoken_nofee(amounts, deposit, swap)
    d_token -= (
        Curve(swap).calc_token_fee(amountsp, xp) * d_token // 10**10 + 1
    )

    return d_token


@external
@view
def calc_fee_get_dy(i: uint256, j: uint256, dx: uint256, swap: address
) -> uint256:

    dy: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    dy, xp = self._get_dy_nofee(i, j, dx, swap)

    return Curve(swap).fee_calc(xp) * dy // 10**10


@external
@view
def calc_fee_withdraw_one_coin(
    token_amount: uint256, i: uint256, swap: address
) -> uint256:

    return self._calc_withdraw_one_coin(token_amount, i, swap)[1]


@view
@external
def calc_fee_token_amount(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> uint256:

    d_token: uint256 = 0
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    d_token, amountsp, xp = self._calc_dtoken_nofee(amounts, deposit, swap)

    return Curve(swap).calc_token_fee(amountsp, xp) * d_token // 10**10 + 1


@internal
@view
def _calc_D_ramp(
    A: uint256,
    gamma: uint256,
    xp: uint256[N_COINS],
    precisions: uint256[N_COINS],
    price_scale: uint256,
    swap: address
) -> uint256:

    math: Math = Curve(swap).MATH()
    D: uint256 = Curve(swap).D()
    if Curve(swap).future_A_gamma_time() > block.timestamp:
        _xp: uint256[N_COINS] = xp
        _xp[0] *= precisions[0]
        _xp[1] = _xp[1] * price_scale * precisions[1] // PRECISION
        D = staticcall math.newton_D(A, gamma, _xp, 0)

    return D


@internal
@view
def _get_dx_fee(
    i: uint256, j: uint256, dy: uint256, swap: address
) -> (uint256, uint256[N_COINS]):

    # here, dy must include fees (and 1 wei offset)

    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    assert dy > 0, "do not exchange out 0 coins"

    math: Math = Curve(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    # adjust xp with output dy. dy contains fee element, which we handle later
    # (hence this internal method is called _get_dx_fee)
    xp[j] -= dy
    xp = [xp[0] * precisions[0], xp[1] * price_scale * precisions[1] // PRECISION]

    x_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, i)
    dx: uint256 = x_out[0] - xp[i]
    xp[i] = x_out[0]

    if i > 0:
        dx = dx * PRECISION // price_scale
    dx //= precisions[i]

    return dx, xp


@internal
@view
def _get_dy_nofee(
    i: uint256, j: uint256, dx: uint256, swap: address
) -> (uint256, uint256[N_COINS]):

    assert i != j and i < N_COINS and j < N_COINS, "coin index out of range"
    assert dx > 0, "do not exchange 0 coins"

    math: Math = Curve(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    # adjust xp with input dx
    xp[i] += dx
    xp = [
        xp[0] * precisions[0],
        xp[1] * price_scale * precisions[1] // PRECISION
    ]

    y_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, j)

    dy: uint256 = xp[j] - y_out[0] - 1
    xp[j] = y_out[0]
    if j > 0:
        dy = dy * PRECISION // price_scale
    dy //= precisions[j]

    return dy, xp


@internal
@view
def _calc_dtoken_nofee(
    amounts: uint256[N_COINS], deposit: bool, swap: address
) -> (uint256, uint256[N_COINS], uint256[N_COINS]):

    math: Math = Curve(swap).MATH()

    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    price_scale: uint256 = 0
    D0: uint256 = 0
    token_supply: uint256 = 0
    A: uint256 = 0
    gamma: uint256 = 0

    xp, D0, token_supply, price_scale, A, gamma, precisions = self._prep_calc(swap)

    amountsp: uint256[N_COINS] = amounts
    if deposit:
        for k: uint256 in range(N_COINS):
            xp[k] += amounts[k]
    else:
        for k: uint256 in range(N_COINS):
            xp[k] -= amounts[k]

    xp = [
        xp[0] * precisions[0],
        xp[1] * price_scale * precisions[1] // PRECISION
    ]
    amountsp = [
        amountsp[0]* precisions[0],
        amountsp[1] * price_scale * precisions[1] // PRECISION
    ]

    D: uint256 = staticcall math.newton_D(A, gamma, xp, 0)
    d_token: uint256 = token_supply * D // D0

    if deposit:
        d_token -= token_supply
    else:
        d_token = token_supply - d_token

    return d_token, amountsp, xp


@internal
@view
def _calc_withdraw_one_coin(
    token_amount: uint256,
    i: uint256,
    swap: address
) -> (uint256, uint256):

    token_supply: uint256 = Curve(swap).totalSupply()
    assert token_amount <= token_supply  # dev: token amount more than supply
    assert i < N_COINS  # dev: coin out of range

    math: Math = Curve(swap).MATH()

    xx: uint256[N_COINS] = empty(uint256[N_COINS])
    for k: uint256 in range(N_COINS):
        xx[k] = Curve(swap).balances(k)

    precisions: uint256[N_COINS] = Curve(swap).precisions()
    A: uint256 = Curve(swap).A()
    gamma: uint256 = Curve(swap).gamma()
    D0: uint256 = 0
    p: uint256 = 0

    price_scale_i: uint256 = Curve(swap).price_scale() * precisions[1]
    xp: uint256[N_COINS] = [
        xx[0] * precisions[0],
        unsafe_div(xx[1] * price_scale_i, PRECISION)
    ]
    if i == 0:
        price_scale_i = PRECISION * precisions[0]

    if Curve(swap).future_A_gamma_time() > block.timestamp:
        D0 = staticcall math.newton_D(A, gamma, xp, 0)
    else:
        D0 = Curve(swap).D()

    D: uint256 = D0

    fee: uint256 = self._fee(xp, swap)
    dD: uint256 = token_amount * D // token_supply

    D_fee: uint256 = fee * dD // (2 * 10**10) + 1
    approx_fee: uint256 = N_COINS * D_fee * xx[i] // D

    D -= (dD - D_fee)

    y_out: uint256[2] = staticcall math.get_y(A, gamma, xp, D, i)
    dy: uint256 = (xp[i] - y_out[0]) * PRECISION // price_scale_i
    xp[i] = y_out[0]

    return dy, approx_fee


@internal
@view
def _fee(xp: uint256[N_COINS], swap: address) -> uint256:

    packed_fee_params: uint256 = Curve(swap).packed_fee_params()
    fee_params: uint256[3] = self._unpack_3(packed_fee_params)
    f: uint256 = xp[0] + xp[1]
    f = fee_params[2] * 10**18 // (
        fee_params[2] + 10**18 -
        (10**18 * N_COINS**N_COINS) * xp[0] // f * xp[1] // f
    )

    return (fee_params[0] * f + fee_params[1] * (10**18 - f)) // 10**18


@internal
@view
def _prep_calc(swap: address) -> (
    uint256[N_COINS],
    uint256,
    uint256,
    uint256,
    uint256,
    uint256,
    uint256[N_COINS]
):

    precisions: uint256[N_COINS] = Curve(swap).precisions()
    token_supply: uint256 = Curve(swap).totalSupply()
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    for k: uint256 in range(N_COINS):
        xp[k] = Curve(swap).balances(k)

    price_scale: uint256 = Curve(swap).price_scale()

    A: uint256 = Curve(swap).A()
    gamma: uint256 = Curve(swap).gamma()
    D: uint256 = self._calc_D_ramp(
        A, gamma, xp, precisions, price_scale, swap
    )

    return xp, D, token_supply, price_scale, A, gamma, precisions


@internal
@view
def _unpack_3(_packed: uint256) -> uint256[3]:
    """
    @notice Unpacks a uint256 into 3 integers (values must be <= 10**18)
    @param val The uint256 to unpack
    @return The unpacked uint256[3]
    """
    return [
        (_packed >> 128) & 18446744073709551615,
        (_packed >> 64) & 18446744073709551615,
        _packed & 18446744073709551615,
    ]
