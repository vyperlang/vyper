# adapted from https://github.com/curvefi/curve-crypto-contract/blob/d7d04cd9ae038970e40be850df99de8c1ff7241b/contracts/two/CurveCryptoSwap2.vy
# (c) Curve.Fi, 2021
# Pool for two crypto assets

from ethereum.ercs import IERC20
# Expected coins:
# eur*/3crv
# crypto/tricrypto
# All are proper ERC20s, so let's use a standard interface and save bytespace

interface CurveToken:
    def totalSupply() -> uint256: view
    def mint(_to: address, _value: uint256) -> bool: nonpayable
    def mint_relative(_to: address, frac: uint256) -> uint256: nonpayable
    def burnFrom(_to: address, _value: uint256) -> bool: nonpayable


# Events
event TokenExchange:
    buyer: indexed(address)
    sold_id: uint256
    tokens_sold: uint256
    bought_id: uint256
    tokens_bought: uint256

event AddLiquidity:
    provider: indexed(address)
    token_amounts: uint256[N_COINS]
    fee: uint256
    token_supply: uint256

event RemoveLiquidity:
    provider: indexed(address)
    token_amounts: uint256[N_COINS]
    token_supply: uint256

event RemoveLiquidityOne:
    provider: indexed(address)
    token_amount: uint256
    coin_index: uint256
    coin_amount: uint256

event CommitNewAdmin:
    deadline: indexed(uint256)
    admin: indexed(address)

event NewAdmin:
    admin: indexed(address)

event CommitNewParameters:
    deadline: indexed(uint256)
    admin_fee: uint256
    mid_fee: uint256
    out_fee: uint256
    fee_gamma: uint256
    allowed_extra_profit: uint256
    adjustment_step: uint256
    ma_half_time: uint256

event NewParameters:
    admin_fee: uint256
    mid_fee: uint256
    out_fee: uint256
    fee_gamma: uint256
    allowed_extra_profit: uint256
    adjustment_step: uint256
    ma_half_time: uint256

event RampAgamma:
    initial_A: uint256
    future_A: uint256
    initial_gamma: uint256
    future_gamma: uint256
    initial_time: uint256
    future_time: uint256

event StopRampA:
    current_A: uint256
    current_gamma: uint256
    time: uint256

event ClaimAdminFee:
    admin: indexed(address)
    tokens: uint256


N_COINS: constant(uint256) = 2
PRECISION: constant(uint256) = 10 ** 18  # The precision to convert to
A_MULTIPLIER: constant(uint256) = 10000

# These addresses are replaced by the deployer
token: public(constant(address)) = 0x0000000000000000000000000000000000000001
coins: public(constant(address[N_COINS])) = [
    0x0000000000000000000000000000000000000010,
    0x0000000000000000000000000000000000000011]

price_scale: public(uint256)   # Internal price scale
price_oracle: public(uint256)  # Price target given by MA

last_prices: public(uint256)
last_prices_timestamp: public(uint256)

initial_A_gamma: public(uint256)
future_A_gamma: public(uint256)
initial_A_gamma_time: public(uint256)
future_A_gamma_time: public(uint256)

allowed_extra_profit: public(uint256)  # 2 * 10**12 - recommended value
future_allowed_extra_profit: public(uint256)

fee_gamma: public(uint256)
future_fee_gamma: public(uint256)

adjustment_step: public(uint256)
future_adjustment_step: public(uint256)

ma_half_time: public(uint256)
future_ma_half_time: public(uint256)

mid_fee: public(uint256)
out_fee: public(uint256)
admin_fee: public(uint256)
future_mid_fee: public(uint256)
future_out_fee: public(uint256)
future_admin_fee: public(uint256)

balances: public(uint256[N_COINS])
D: public(uint256)

owner: public(address)
future_owner: public(address)

xcp_profit: public(uint256)
xcp_profit_a: public(uint256)  # Full profit at last claim of admin fees
virtual_price: public(uint256)  # Cached (fast to read) virtual price also used internally
not_adjusted: bool

is_killed: public(bool)
kill_deadline: public(uint256)
transfer_ownership_deadline: public(uint256)
admin_actions_deadline: public(uint256)

admin_fee_receiver: public(address)

KILL_DEADLINE_DT: constant(uint256) = 2 * 30 * 86400
ADMIN_ACTIONS_DELAY: constant(uint256) = 3 * 86400
MIN_RAMP_TIME: constant(uint256) = 86400

MAX_ADMIN_FEE: constant(uint256) = 10 * 10 ** 9
MIN_FEE: constant(uint256) = 5 * 10 ** 5  # 0.5 bps
MAX_FEE: constant(uint256) = 10 * 10 ** 9
MAX_A_CHANGE: constant(uint256) = 10
NOISE_FEE: constant(uint256) = 10**5  # 0.1 bps

MIN_GAMMA: constant(uint256) = 10**10
MAX_GAMMA: constant(uint256) = 5 * 10**16

MIN_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER // 100
MAX_A: constant(uint256) = N_COINS**N_COINS * A_MULTIPLIER * 10000

# This must be changed for different N_COINS
# For example:
# N_COINS = 3 -> 1  (10**18 -> 10**18)
# N_COINS = 4 -> 10**8  (10**18 -> 10**10)
# PRICE_PRECISION_MUL: constant(uint256) = 1
PRECISIONS: constant(uint256[N_COINS]) = [
    1,#0
    1,#1
]

EXP_PRECISION: constant(uint256) = 10**10


@deploy
def __init__(
    owner: address,
    admin_fee_receiver: address,
    A: uint256,
    gamma: uint256,
    mid_fee: uint256,
    out_fee: uint256,
    allowed_extra_profit: uint256,
    fee_gamma: uint256,
    adjustment_step: uint256,
    admin_fee: uint256,
    ma_half_time: uint256,
    initial_price: uint256
):
    self.owner = owner

    # Pack A and gamma:
    # shifted A + gamma
    A_gamma: uint256 = A << 128
    A_gamma = A_gamma | gamma
    self.initial_A_gamma = A_gamma
    self.future_A_gamma = A_gamma

    self.mid_fee = mid_fee
    self.out_fee = out_fee
    self.allowed_extra_profit = allowed_extra_profit
    self.fee_gamma = fee_gamma
    self.adjustment_step = adjustment_step
    self.admin_fee = admin_fee

    self.price_scale = initial_price
    self.price_oracle = initial_price
    self.last_prices = initial_price
    self.last_prices_timestamp = block.timestamp
    self.ma_half_time = ma_half_time

    self.xcp_profit_a = 10**18

    self.kill_deadline = block.timestamp + KILL_DEADLINE_DT

    self.admin_fee_receiver = admin_fee_receiver


### Math functions
@internal
@pure
def geometric_mean(unsorted_x: uint256[N_COINS], sort: bool) -> uint256:
    """
    (x[0] * x[1] * ...) ** (1/N)
    """
    x: uint256[N_COINS] = unsorted_x
    if sort and x[0] < x[1]:
        x = [unsorted_x[1], unsorted_x[0]]
    D: uint256 = x[0]
    diff: uint256 = 0
    for i: uint256 in range(255):
        D_prev: uint256 = D
        # tmp: uint256 = 10**18
        # for _x in x:
        #     tmp = tmp * _x // D
        # D = D * ((N_COINS - 1) * 10**18 + tmp) // (N_COINS * 10**18)
        # line below makes it for 2 coins
        D = (D + x[0] * x[1] // D) // N_COINS
        if D > D_prev:
            diff = D - D_prev
        else:
            diff = D_prev - D
        if diff <= 1 or diff * 10**18 < D:
            return D
    raise "Did not converge"


@internal
@view
def newton_D(ANN: uint256, gamma: uint256, x_unsorted: uint256[N_COINS]) -> uint256:
    """
    Finding the invariant using Newton method.
    ANN is higher by the factor A_MULTIPLIER
    ANN is already A * N**N

    Currently uses 60k gas
    """
    # Safety checks
    assert ANN > MIN_A - 1 and ANN < MAX_A + 1  # dev: unsafe values A
    assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1  # dev: unsafe values gamma

    # Initial value of invariant D is that for constant-product invariant
    x: uint256[N_COINS] = x_unsorted
    if x[0] < x[1]:
        x = [x_unsorted[1], x_unsorted[0]]

    assert x[0] > 10**9 - 1 and x[0] < 10**15 * 10**18 + 1  # dev: unsafe values x[0]
    assert x[1] * 10**18 // x[0] > 10**14-1  # dev: unsafe values x[i]

    D: uint256 = N_COINS * self.geometric_mean(x, False)
    S: uint256 = x[0] + x[1]

    for i: uint256 in range(255):
        D_prev: uint256 = D

        # K0: uint256 = 10**18
        # for _x in x:
        #     K0 = K0 * _x * N_COINS // D
        # collapsed for 2 coins
        K0: uint256 = (10**18 * N_COINS**2) * x[0] // D * x[1] // D

        _g1k0: uint256 = gamma + 10**18
        if _g1k0 > K0:
            _g1k0 = _g1k0 - K0 + 1
        else:
            _g1k0 = K0 - _g1k0 + 1

        # D // (A * N**N) * _g1k0**2 // gamma**2
        mul1: uint256 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN

        # 2*N*K0 // _g1k0
        mul2: uint256 = (2 * 10**18) * N_COINS * K0 // _g1k0

        neg_fprime: uint256 = (S + S * mul2 // 10**18) + mul1 * N_COINS // K0 - mul2 * D // 10**18

        # D -= f // fprime
        D_plus: uint256 = D * (neg_fprime + S) // neg_fprime
        D_minus: uint256 = D*D // neg_fprime
        if 10**18 > K0:
            D_minus += D * (mul1 // neg_fprime) // 10**18 * (10**18 - K0) // K0
        else:
            D_minus -= D * (mul1 // neg_fprime) // 10**18 * (K0 - 10**18) // K0

        if D_plus > D_minus:
            D = D_plus - D_minus
        else:
            D = (D_minus - D_plus) // 2

        diff: uint256 = 0
        if D > D_prev:
            diff = D - D_prev
        else:
            diff = D_prev - D
        if diff * 10**14 < max(10**16, D):  # Could reduce precision for gas efficiency here
            # Test that we are safe with the next newton_y
            for _x: uint256 in x:
                frac: uint256 = _x * 10**18 // D
                assert (frac > 10**16 - 1) and (frac < 10**20 + 1)  # dev: unsafe values x[i]
            return D

    raise "Did not converge"


@internal
@pure
def newton_y(ANN: uint256, gamma: uint256, x: uint256[N_COINS], D: uint256, i: uint256) -> uint256:
    """
    Calculating x[i] given other balances x[0..N_COINS-1] and invariant D
    ANN = A * N**N
    """
    # Safety checks
    assert ANN > MIN_A - 1 and ANN < MAX_A + 1  # dev: unsafe values A
    assert gamma > MIN_GAMMA - 1 and gamma < MAX_GAMMA + 1  # dev: unsafe values gamma
    assert D > 10**17 - 1 and D < 10**15 * 10**18 + 1 # dev: unsafe values D

    x_j: uint256 = x[1 - i]
    y: uint256 = D**2 // (x_j * N_COINS**2)
    K0_i: uint256 = (10**18 * N_COINS) * x_j // D
    # S_i = x_j

    # frac = x_j * 1e18 // D => frac = K0_i // N_COINS
    assert (K0_i > 10**16*N_COINS - 1) and (K0_i < 10**20*N_COINS + 1)  # dev: unsafe values x[i]

    # x_sorted: uint256[N_COINS] = x
    # x_sorted[i] = 0
    # x_sorted = self.sort(x_sorted)  # From high to low
    # x[not i] instead of x_sorted since x_soted has only 1 element

    convergence_limit: uint256 = max(max(x_j // 10**14, D // 10**14), 100)

    for j: uint256 in range(255):
        y_prev: uint256 = y

        K0: uint256 = K0_i * y * N_COINS // D
        S: uint256 = x_j + y

        _g1k0: uint256 = gamma + 10**18
        if _g1k0 > K0:
            _g1k0 = _g1k0 - K0 + 1
        else:
            _g1k0 = K0 - _g1k0 + 1

        # D // (A * N**N) * _g1k0**2 // gamma**2
        mul1: uint256 = 10**18 * D // gamma * _g1k0 // gamma * _g1k0 * A_MULTIPLIER // ANN

        # 2*K0 // _g1k0
        mul2: uint256 = 10**18 + (2 * 10**18) * K0 // _g1k0

        yfprime: uint256 = 10**18 * y + S * mul2 + mul1
        _dyfprime: uint256 = D * mul2
        if yfprime < _dyfprime:
            y = y_prev // 2
            continue
        else:
            yfprime -= _dyfprime
        fprime: uint256 = yfprime // y

        # y -= f // f_prime;  y = (y * fprime - f) // fprime
        # y = (yfprime + 10**18 * D - 10**18 * S) // fprime + mul1 // fprime * (10**18 - K0) // K0
        y_minus: uint256 = mul1 // fprime
        y_plus: uint256 = (yfprime + 10**18 * D) // fprime + y_minus * 10**18 // K0
        y_minus += 10**18 * S // fprime

        if y_plus < y_minus:
            y = y_prev // 2
        else:
            y = y_plus - y_minus

        diff: uint256 = 0
        if y > y_prev:
            diff = y - y_prev
        else:
            diff = y_prev - y
        if diff < max(convergence_limit, y // 10**14):
            frac: uint256 = y * 10**18 // D
            assert (frac > 10**16 - 1) and (frac < 10**20 + 1)  # dev: unsafe value for y
            return y

    raise "Did not converge"


@internal
@pure
def halfpow(power: uint256) -> uint256:
    """
    1e18 * 0.5 ** (power/1e18)

    Inspired by: https://github.com/balancer-labs/balancer-core/blob/master/contracts/BNum.sol#L128
    """
    intpow: uint256 = power // 10**18
    otherpow: uint256 = power - intpow * 10**18
    if intpow > 59:
        return 0
    result: uint256 = 10**18 // (2**intpow)
    if otherpow == 0:
        return result

    term: uint256 = 10**18
    x: uint256 = 5 * 10**17
    S: uint256 = 10**18
    neg: bool = False

    for i: uint256 in range(1, 256):
        K: uint256 = i * 10**18
        c: uint256 = K - 10**18
        if otherpow > c:
            c = otherpow - c
            neg = not neg
        else:
            c -= otherpow
        term = term * (c * x // 10**18) // K
        if neg:
            S -= term
        else:
            S += term
        if term < EXP_PRECISION:
            return result * S // 10**18

    raise "Did not converge"
### end of Math functions


@internal
@view
def xp() -> uint256[N_COINS]:
    return [self.balances[0] * PRECISIONS[0],
            self.balances[1] * PRECISIONS[1] * self.price_scale // PRECISION]


@view
@internal
def _A_gamma() -> uint256[2]:
    t1: uint256 = self.future_A_gamma_time

    A_gamma_1: uint256 = self.future_A_gamma
    gamma1: uint256 = A_gamma_1 & (2**128-1)
    A1: uint256 = A_gamma_1 >> 128

    if block.timestamp < t1:
        # handle ramping up and down of A
        A_gamma_0: uint256 = self.initial_A_gamma
        t0: uint256 = self.initial_A_gamma_time

        # Less readable but more compact way of writing and converting to uint256
        # gamma0: uint256 = A_gamma_0 & (2**128-1)
        # A0: uint256 = A_gamma_0 >> 128
        # A1 = A0 + (A1 - A0) * (block.timestamp - t0) // (t1 - t0)
        # gamma1 = gamma0 + (gamma1 - gamma0) * (block.timestamp - t0) // (t1 - t0)

        t1 -= t0
        t0 = block.timestamp - t0
        t2: uint256 = t1 - t0

        A1 = ((A_gamma_0 >> 128) * t2 + A1 * t0) // t1
        gamma1 = (A_gamma_0 & (2**128-1) * t2 + gamma1 * t0) // t1

    return [A1, gamma1]


@view
@external
def A() -> uint256:
    return self._A_gamma()[0]


@view
@external
def gamma() -> uint256:
    return self._A_gamma()[1]


@internal
@view
def _fee(xp: uint256[N_COINS]) -> uint256:
    """
    f = fee_gamma // (fee_gamma + (1 - K))
    where
    K = prod(x) // (sum(x) // N)**N
    (all normalized to 1e18)
    """
    fee_gamma: uint256 = self.fee_gamma
    f: uint256 = xp[0] + xp[1]  # sum
    f = fee_gamma * 10**18 // (
        fee_gamma + 10**18 - (10**18 * N_COINS**N_COINS) * xp[0] // f * xp[1] // f
    )
    return (self.mid_fee * f + self.out_fee * (10**18 - f)) // 10**18


@external
@view
def fee() -> uint256:
    return self._fee(self.xp())


@internal
@view
def get_xcp(D: uint256) -> uint256:
    x: uint256[N_COINS] = [D // N_COINS, D * PRECISION // (self.price_scale * N_COINS)]
    return self.geometric_mean(x, True)


@external
@view
def get_virtual_price() -> uint256:
    return 10**18 * self.get_xcp(self.D) // staticcall CurveToken(token).totalSupply()


@internal
def _claim_admin_fees():
    A_gamma: uint256[2] = self._A_gamma()

    xcp_profit: uint256 = self.xcp_profit
    xcp_profit_a: uint256 = self.xcp_profit_a

    # Gulp here
    _coins: address[N_COINS] = coins
    for i: uint256 in range(N_COINS):
        self.balances[i] = staticcall IERC20(_coins[i]).balanceOf(self)

    vprice: uint256 = self.virtual_price

    if xcp_profit > xcp_profit_a:
        fees: uint256 = (xcp_profit - xcp_profit_a) * self.admin_fee // (2 * 10**10)
        if fees > 0:
            receiver: address = self.admin_fee_receiver
            frac: uint256 = vprice * 10**18 // (vprice - fees) - 10**18
            claimed: uint256 = extcall CurveToken(token).mint_relative(receiver, frac)
            xcp_profit -= fees*2
            self.xcp_profit = xcp_profit
            log ClaimAdminFee(admin=receiver, tokens=claimed)

    total_supply: uint256 = staticcall CurveToken(token).totalSupply()

    # Recalculate D b/c we gulped
    D: uint256 = self.newton_D(A_gamma[0], A_gamma[1], self.xp())
    self.D = D

    self.virtual_price = 10**18 * self.get_xcp(D) // total_supply

    if xcp_profit > xcp_profit_a:
        self.xcp_profit_a = xcp_profit


@internal
def tweak_price(A_gamma: uint256[2],_xp: uint256[N_COINS], p_i: uint256, new_D: uint256):
    price_oracle: uint256 = self.price_oracle
    last_prices: uint256 = self.last_prices
    price_scale: uint256 = self.price_scale
    last_prices_timestamp: uint256 = self.last_prices_timestamp
    p_new: uint256 = 0

    if last_prices_timestamp < block.timestamp:
        # MA update required
        ma_half_time: uint256 = self.ma_half_time
        alpha: uint256 = self.halfpow((block.timestamp - last_prices_timestamp) * 10**18 // ma_half_time)
        price_oracle = (last_prices * (10**18 - alpha) + price_oracle * alpha) // 10**18
        self.price_oracle = price_oracle
        self.last_prices_timestamp = block.timestamp

    D_unadjusted: uint256 = new_D  # Withdrawal methods know new D already
    if new_D == 0:
        # We will need this a few times (35k gas)
        D_unadjusted = self.newton_D(A_gamma[0], A_gamma[1], _xp)

    if p_i > 0:
        last_prices = p_i

    else:
        # calculate real prices
        __xp: uint256[N_COINS] = _xp
        dx_price: uint256 = __xp[0] // 10**6
        __xp[0] += dx_price
        last_prices = price_scale * dx_price // (_xp[1] - self.newton_y(A_gamma[0], A_gamma[1], __xp, D_unadjusted, 1))

    self.last_prices = last_prices

    total_supply: uint256 = staticcall CurveToken(token).totalSupply()
    old_xcp_profit: uint256 = self.xcp_profit
    old_virtual_price: uint256 = self.virtual_price

    # Update profit numbers without price adjustment first
    xp: uint256[N_COINS] = [D_unadjusted // N_COINS, D_unadjusted * PRECISION // (N_COINS * price_scale)]
    xcp_profit: uint256 = 10**18
    virtual_price: uint256 = 10**18

    if old_virtual_price > 0:
        xcp: uint256 = self.geometric_mean(xp, True)
        virtual_price = 10**18 * xcp // total_supply
        xcp_profit = old_xcp_profit * virtual_price // old_virtual_price

        t: uint256 = self.future_A_gamma_time
        if virtual_price < old_virtual_price and t == 0:
            raise "Loss"
        if t == 1:
            self.future_A_gamma_time = 0

    self.xcp_profit = xcp_profit

    needs_adjustment: bool = self.not_adjusted
    # if not needs_adjustment and (virtual_price-10**18 > (xcp_profit-10**18)/2 + self.allowed_extra_profit):
    # (re-arrange for gas efficiency)
    if not needs_adjustment and (virtual_price * 2 - 10**18 > xcp_profit + 2*self.allowed_extra_profit):
        needs_adjustment = True
        self.not_adjusted = True

    if needs_adjustment:
        adjustment_step: uint256 = self.adjustment_step
        norm: uint256 = price_oracle * 10**18 // price_scale
        if norm > 10**18:
            norm -= 10**18
        else:
            norm = 10**18 - norm

        if norm > adjustment_step and old_virtual_price > 0:
            p_new = (price_scale * (norm - adjustment_step) + adjustment_step * price_oracle) // norm

            # Calculate balances*prices
            xp = [_xp[0], _xp[1] * p_new // price_scale]

            # Calculate "extended constant product" invariant xCP and virtual price
            D: uint256 = self.newton_D(A_gamma[0], A_gamma[1], xp)
            xp = [D // N_COINS, D * PRECISION // (N_COINS * p_new)]
            # We reuse old_virtual_price here but it's not old anymore
            old_virtual_price = 10**18 * self.geometric_mean(xp, True) // total_supply

            # Proceed if we've got enough profit
            # if (old_virtual_price > 10**18) and (2 * (old_virtual_price - 10**18) > xcp_profit - 10**18):
            if (old_virtual_price > 10**18) and (2 * old_virtual_price - 10**18 > xcp_profit):
                self.price_scale = p_new
                self.D = D
                self.virtual_price = old_virtual_price

                return

            else:
                self.not_adjusted = False

    # If we are here, the price_scale adjustment did not happen
    # Still need to update the profit counter and D
    self.D = D_unadjusted
    self.virtual_price = virtual_price



@external
def exchange(i: uint256, j: uint256, dx: uint256, min_dy: uint256):
    assert not self.is_killed  # dev: the pool is killed
    assert i != j  # dev: coin index out of range
    assert i < N_COINS  # dev: coin index out of range
    assert j < N_COINS  # dev: coin index out of range
    assert dx > 0  # dev: do not exchange 0 coins

    A_gamma: uint256[2] = self._A_gamma()
    xp: uint256[N_COINS] = self.balances
    p: uint256 = 0
    dy: uint256 = 0

    if True:  # scope to reduce size of memory when making internal calls later
        _coins: address[N_COINS] = coins
        assert extcall IERC20(_coins[i]).transferFrom(msg.sender, self, dx)

        y: uint256 = xp[j]
        x0: uint256 = xp[i]
        xp[i] = x0 + dx
        self.balances[i] = xp[i]

        price_scale: uint256 = self.price_scale

        xp = [xp[0] * PRECISIONS[0], xp[1] * price_scale * PRECISIONS[1] // PRECISION]

        prec_i: uint256 = PRECISIONS[0]
        prec_j: uint256 = PRECISIONS[1]
        if i == 1:
            prec_i = PRECISIONS[1]
            prec_j = PRECISIONS[0]

        # In case ramp is happening
        if True:
            t: uint256 = self.future_A_gamma_time
            if t > 0:
                x0 *= prec_i
                if i > 0:
                    x0 = x0 * price_scale // PRECISION
                x1: uint256 = xp[i]  # Back up old value in xp
                xp[i] = x0
                self.D = self.newton_D(A_gamma[0], A_gamma[1], xp)
                xp[i] = x1  # And restore
                if block.timestamp >= t:
                    self.future_A_gamma_time = 1

        dy = xp[j] - self.newton_y(A_gamma[0], A_gamma[1], xp, self.D, j)
        # Not defining new "y" here to have less variables // make subsequent calls cheaper
        xp[j] -= dy
        dy -= 1

        if j > 0:
            dy = dy * PRECISION // price_scale
        dy //= prec_j

        dy -= self._fee(xp) * dy // 10**10
        assert dy >= min_dy, "Slippage"
        y -= dy

        self.balances[j] = y
        assert extcall IERC20(_coins[j]).transfer(msg.sender, dy)

        y *= prec_j
        if j > 0:
            y = y * price_scale // PRECISION
        xp[j] = y

        # Calculate price
        if dx > 10**5 and dy > 10**5:
            _dx: uint256 = dx * prec_i
            _dy: uint256 = dy * prec_j
            if i == 0:
                p = _dx * 10**18 // _dy
            else:  # j == 0
                p = _dy * 10**18 // _dx

    self.tweak_price(A_gamma, xp, p, 0)

    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=dx, bought_id=j, tokens_bought=dy)


@external
@view
def get_dy(i: uint256, j: uint256, dx: uint256) -> uint256:
    assert i != j  # dev: same input and output coin
    assert i < N_COINS  # dev: coin index out of range
    assert j < N_COINS  # dev: coin index out of range

    price_scale: uint256 = self.price_scale * PRECISIONS[1]
    xp: uint256[N_COINS] = self.balances
    xp[i] += dx
    xp = [xp[0] * PRECISIONS[0], xp[1] * price_scale // PRECISION]

    A: uint256 = 0
    gamma: uint256 = 0
    A_gamma: uint256[2] = self._A_gamma()

    D: uint256 = self.newton_D(A_gamma[0], A_gamma[1], xp)
    y: uint256 = self.newton_y(A_gamma[0], A_gamma[1], xp, D, j)
    dy: uint256 = xp[j] - y - 1
    xp[j] = y
    if j > 0:
        dy = dy * PRECISION // price_scale
    else:
        dy //= PRECISIONS[0]
    dy -= self._fee(xp) * dy // 10**10

    return dy


@view
@internal
def _calc_token_fee(amounts: uint256[N_COINS], xp: uint256[N_COINS]) -> uint256:
    # fee = sum(amounts_i - avg(amounts)) * fee' // sum(amounts)
    fee: uint256 = self._fee(xp) * N_COINS // (4 * (N_COINS-1))
    S: uint256 = 0
    for _x: uint256 in amounts:
        S += _x
    avg: uint256 = S // N_COINS
    Sdiff: uint256 = 0
    for _x: uint256 in amounts:
        if _x > avg:
            Sdiff += _x - avg
        else:
            Sdiff += avg - _x
    return fee * Sdiff // S + NOISE_FEE


@external
def add_liquidity(amounts: uint256[N_COINS], min_mint_amount: uint256):
    assert not self.is_killed  # dev: the pool is killed

    A_gamma: uint256[2] = self._A_gamma()

    _coins: address[N_COINS] = coins

    xp: uint256[N_COINS] = self.balances
    amountsp: uint256[N_COINS] = empty(uint256[N_COINS])
    xx: uint256[N_COINS] = empty(uint256[N_COINS])
    d_token: uint256 = 0
    d_token_fee: uint256 = 0
    old_D: uint256 = 0

    if True:  # Scope to avoid having extra variables in memory later
        xp_old: uint256[N_COINS] = xp

        for i: uint256 in range(N_COINS):
            bal: uint256 = xp[i] + amounts[i]
            xp[i] = bal
            self.balances[i] = bal
        xx = xp

        price_scale: uint256 = self.price_scale * PRECISIONS[1]
        xp = [xp[0] * PRECISIONS[0], xp[1] * price_scale // PRECISION]
        xp_old = [xp_old[0] * PRECISIONS[0], xp_old[1] * price_scale // PRECISION]

        for i: uint256 in range(N_COINS):
            if amounts[i] > 0:
                assert extcall IERC20(_coins[i]).transferFrom(msg.sender, self, amounts[i])
                amountsp[i] = xp[i] - xp_old[i]
        assert amounts[0] > 0 or amounts[1] > 0  # dev: no coins to add

        t: uint256 = self.future_A_gamma_time
        if t > 0:
            old_D = self.newton_D(A_gamma[0], A_gamma[1], xp_old)
            if block.timestamp >= t:
                self.future_A_gamma_time = 1
        else:
            old_D = self.D

    D: uint256 = self.newton_D(A_gamma[0], A_gamma[1], xp)

    token_supply: uint256 = staticcall CurveToken(token).totalSupply()
    if old_D > 0:
        d_token = token_supply * D // old_D - token_supply
    else:
        d_token = self.get_xcp(D)  # making initial virtual price equal to 1
    assert d_token > 0  # dev: nothing minted

    if old_D > 0:
        d_token_fee = self._calc_token_fee(amountsp, xp) * d_token // 10**10 + 1
        d_token -= d_token_fee
        token_supply += d_token
        extcall CurveToken(token).mint(msg.sender, d_token)

        # Calculate price
        # p_i * (dx_i - dtoken // token_supply * xx_i) = sum{k!=i}(p_k * (dtoken // token_supply * xx_k - dx_k))
        # Simplified for 2 coins
        p: uint256 = 0
        if d_token > 10**5:
            if amounts[0] == 0 or amounts[1] == 0:
                S: uint256 = 0
                precision: uint256 = 0
                ix: uint256 = 0
                if amounts[0] == 0:
                    S = xx[0] * PRECISIONS[0]
                    precision = PRECISIONS[1]
                    ix = 1
                else:
                    S = xx[1] * PRECISIONS[1]
                    precision = PRECISIONS[0]
                S = S * d_token // token_supply
                p = S * PRECISION // (amounts[ix] * precision - d_token * xx[ix] * precision // token_supply)
                if ix == 0:
                    p = (10**18)**2 // p

        self.tweak_price(A_gamma, xp, p, D)

    else:
        self.D = D
        self.virtual_price = 10**18
        self.xcp_profit = 10**18
        extcall CurveToken(token).mint(msg.sender, d_token)

    assert d_token >= min_mint_amount, "Slippage"

    log AddLiquidity(provider=msg.sender, token_amounts=amounts, fee=d_token_fee, token_supply=token_supply)


@external
def remove_liquidity(_amount: uint256, min_amounts: uint256[N_COINS]):
    """
    This withdrawal method is very safe, does no complex math
    """
    _coins: address[N_COINS] = coins
    total_supply: uint256 = staticcall CurveToken(token).totalSupply()
    extcall CurveToken(token).burnFrom(msg.sender, _amount)
    balances: uint256[N_COINS] = self.balances
    amount: uint256 = _amount - 1  # Make rounding errors favoring other LPs a tiny bit

    for i: uint256 in range(N_COINS):
        d_balance: uint256 = balances[i] * amount // total_supply
        assert d_balance >= min_amounts[i]
        self.balances[i] = balances[i] - d_balance
        balances[i] = d_balance  # now it's the amounts going out
        assert extcall IERC20(_coins[i]).transfer(msg.sender, d_balance)

    D: uint256 = self.D
    self.D = D - D * amount // total_supply

    log RemoveLiquidity(provider=msg.sender, token_amounts=balances, token_supply=total_supply - _amount)


@view
@external
def calc_token_amount(amounts: uint256[N_COINS]) -> uint256:
    token_supply: uint256 = staticcall CurveToken(token).totalSupply()
    price_scale: uint256 = self.price_scale * PRECISIONS[1]
    A_gamma: uint256[2] = self._A_gamma()
    xp: uint256[N_COINS] = self.xp()
    amountsp: uint256[N_COINS] = [
        amounts[0] * PRECISIONS[0],
        amounts[1] * price_scale // PRECISION]
    D0: uint256 = self.newton_D(A_gamma[0], A_gamma[1], xp)
    xp[0] += amountsp[0]
    xp[1] += amountsp[1]
    D: uint256 = self.newton_D(A_gamma[0], A_gamma[1], xp)
    d_token: uint256 = token_supply * D // D0 - token_supply
    d_token -= self._calc_token_fee(amountsp, xp) * d_token // 10**10 + 1
    return d_token


@internal
@view
def _calc_withdraw_one_coin(A_gamma: uint256[2], token_amount: uint256, i: uint256, update_D: bool,
                            calc_price: bool) -> (uint256, uint256, uint256, uint256[N_COINS]):
    token_supply: uint256 = staticcall CurveToken(token).totalSupply()
    assert token_amount <= token_supply  # dev: token amount more than supply
    assert i < N_COINS  # dev: coin out of range

    xx: uint256[N_COINS] = self.balances
    D0: uint256 = 0

    price_scale_i: uint256 = self.price_scale * PRECISIONS[1]
    xp: uint256[N_COINS] = [xx[0] * PRECISIONS[0], xx[1] * price_scale_i // PRECISION]
    if i == 0:
        price_scale_i = PRECISION * PRECISIONS[0]

    if update_D:
        D0 = self.newton_D(A_gamma[0], A_gamma[1], xp)
    else:
        D0 = self.D

    D: uint256 = D0

    # Charge the fee on D, not on y, e.g. reducing invariant LESS than charging the user
    fee: uint256 = self._fee(xp)
    dD: uint256 = token_amount * D // token_supply
    D -= (dD - (fee * dD // (2 * 10**10) + 1))
    y: uint256 = self.newton_y(A_gamma[0], A_gamma[1], xp, D, i)
    dy: uint256 = (xp[i] - y) * PRECISION // price_scale_i
    xp[i] = y

    # Price calc
    p: uint256 = 0
    if calc_price and dy > 10**5 and token_amount > 10**5:
        # p_i = dD // D0 * sum'(p_k * x_k) // (dy - dD // D0 * y0)
        S: uint256 = 0
        precision: uint256 = PRECISIONS[0]
        if i == 1:
            S = xx[0] * PRECISIONS[0]
            precision = PRECISIONS[1]
        else:
            S = xx[1] * PRECISIONS[1]
        S = S * dD // D0
        p = S * PRECISION // (dy * precision - dD * xx[i] * precision // D0)
        if i == 0:
            p = (10**18)**2 // p

    return dy, p, D, xp


@view
@external
def calc_withdraw_one_coin(token_amount: uint256, i: uint256) -> uint256:
    return self._calc_withdraw_one_coin(self._A_gamma(), token_amount, i, True, False)[0]


@external
def remove_liquidity_one_coin(token_amount: uint256, i: uint256, min_amount: uint256):
    assert not self.is_killed  # dev: the pool is killed

    A_gamma: uint256[2] = self._A_gamma()

    dy: uint256 = 0
    D: uint256 = 0
    p: uint256 = 0
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    future_A_gamma_time: uint256 = self.future_A_gamma_time
    dy, p, D, xp = self._calc_withdraw_one_coin(A_gamma, token_amount, i, (future_A_gamma_time > 0), True)
    assert dy >= min_amount, "Slippage"

    if block.timestamp >= future_A_gamma_time:
        self.future_A_gamma_time = 1

    self.balances[i] -= dy
    extcall CurveToken(token).burnFrom(msg.sender, token_amount)
    self.tweak_price(A_gamma, xp, p, D)

    _coins: address[N_COINS] = coins
    assert extcall IERC20(_coins[i]).transfer(msg.sender, dy)

    log RemoveLiquidityOne(provider=msg.sender, token_amount=token_amount, coin_index=i, coin_amount=dy)


@external
def claim_admin_fees():
    self._claim_admin_fees()


# Admin parameters
@external
def ramp_A_gamma(future_A: uint256, future_gamma: uint256, future_time: uint256):
    assert msg.sender == self.owner  # dev: only owner
    assert block.timestamp > self.initial_A_gamma_time + (MIN_RAMP_TIME-1)
    assert future_time > block.timestamp + (MIN_RAMP_TIME-1)  # dev: insufficient time

    A_gamma: uint256[2] = self._A_gamma()
    initial_A_gamma: uint256 = A_gamma[0] << 128
    initial_A_gamma = initial_A_gamma | A_gamma[1]

    assert future_A > 0
    assert future_A < MAX_A+1
    assert future_gamma > MIN_GAMMA-1
    assert future_gamma < MAX_GAMMA+1

    ratio: uint256 = 10**18 * future_A // A_gamma[0]
    assert ratio < 10**18 * MAX_A_CHANGE + 1
    assert ratio > 10**18 // MAX_A_CHANGE - 1

    ratio = 10**18 * future_gamma // A_gamma[1]
    assert ratio < 10**18 * MAX_A_CHANGE + 1
    assert ratio > 10**18 // MAX_A_CHANGE - 1

    self.initial_A_gamma = initial_A_gamma
    self.initial_A_gamma_time = block.timestamp

    future_A_gamma: uint256 = future_A << 128
    future_A_gamma = future_A_gamma | future_gamma
    self.future_A_gamma_time = future_time
    self.future_A_gamma = future_A_gamma

    log RampAgamma(initial_A=A_gamma[0], future_A=future_A, initial_gamma=A_gamma[1], future_gamma=future_gamma, initial_time=block.timestamp, future_time=future_time)


@external
def stop_ramp_A_gamma():
    assert msg.sender == self.owner  # dev: only owner

    A_gamma: uint256[2] = self._A_gamma()
    current_A_gamma: uint256 = A_gamma[0] << 128
    current_A_gamma = current_A_gamma | A_gamma[1]
    self.initial_A_gamma = current_A_gamma
    self.future_A_gamma = current_A_gamma
    self.initial_A_gamma_time = block.timestamp
    self.future_A_gamma_time = block.timestamp
    # now (block.timestamp < t1) is always False, so we return saved A

    log StopRampA(current_A=A_gamma[0], current_gamma=A_gamma[1], time=block.timestamp)


@external
def commit_new_parameters(
    _new_mid_fee: uint256,
    _new_out_fee: uint256,
    _new_admin_fee: uint256,
    _new_fee_gamma: uint256,
    _new_allowed_extra_profit: uint256,
    _new_adjustment_step: uint256,
    _new_ma_half_time: uint256,
    ):
    assert msg.sender == self.owner  # dev: only owner
    assert self.admin_actions_deadline == 0  # dev: active action

    new_mid_fee: uint256 = _new_mid_fee
    new_out_fee: uint256 = _new_out_fee
    new_admin_fee: uint256 = _new_admin_fee
    new_fee_gamma: uint256 = _new_fee_gamma
    new_allowed_extra_profit: uint256 = _new_allowed_extra_profit
    new_adjustment_step: uint256 = _new_adjustment_step
    new_ma_half_time: uint256 = _new_ma_half_time

    # Fees
    if new_out_fee < MAX_FEE+1:
        assert new_out_fee > MIN_FEE-1  # dev: fee is out of range
    else:
        new_out_fee = self.out_fee
    if new_mid_fee > MAX_FEE:
        new_mid_fee = self.mid_fee
    assert new_mid_fee <= new_out_fee  # dev: mid-fee is too high
    if new_admin_fee > MAX_ADMIN_FEE:
        new_admin_fee = self.admin_fee

    # AMM parameters
    if new_fee_gamma < 10**18:
        assert new_fee_gamma > 0  # dev: fee_gamma out of range [1 .. 10**18]
    else:
        new_fee_gamma = self.fee_gamma
    if new_allowed_extra_profit > 10**18:
        new_allowed_extra_profit = self.allowed_extra_profit
    if new_adjustment_step > 10**18:
        new_adjustment_step = self.adjustment_step

    # MA
    if new_ma_half_time < 7*86400:
        assert new_ma_half_time > 0  # dev: MA time should be longer than 1 second
    else:
        new_ma_half_time = self.ma_half_time

    _deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.admin_actions_deadline = _deadline

    self.future_admin_fee = new_admin_fee
    self.future_mid_fee = new_mid_fee
    self.future_out_fee = new_out_fee
    self.future_fee_gamma = new_fee_gamma
    self.future_allowed_extra_profit = new_allowed_extra_profit
    self.future_adjustment_step = new_adjustment_step
    self.future_ma_half_time = new_ma_half_time

    log CommitNewParameters(
            deadline=_deadline,
            admin_fee=new_admin_fee,
            mid_fee=new_mid_fee,
            out_fee=new_out_fee,
            fee_gamma=new_fee_gamma,
            allowed_extra_profit=new_allowed_extra_profit,
            adjustment_step=new_adjustment_step,
            ma_half_time=new_ma_half_time
        )


@external
def apply_new_parameters():
    assert msg.sender == self.owner  # dev: only owner
    assert block.timestamp >= self.admin_actions_deadline  # dev: insufficient time
    assert self.admin_actions_deadline != 0  # dev: no active action

    self.admin_actions_deadline = 0

    admin_fee: uint256 = self.future_admin_fee
    if self.admin_fee != admin_fee:
        self._claim_admin_fees()
        self.admin_fee = admin_fee

    mid_fee: uint256 = self.future_mid_fee
    self.mid_fee = mid_fee
    out_fee: uint256 = self.future_out_fee
    self.out_fee = out_fee
    fee_gamma: uint256 = self.future_fee_gamma
    self.fee_gamma = fee_gamma
    allowed_extra_profit: uint256 = self.future_allowed_extra_profit
    self.allowed_extra_profit = allowed_extra_profit
    adjustment_step: uint256 = self.future_adjustment_step
    self.adjustment_step = adjustment_step
    ma_half_time: uint256 = self.future_ma_half_time
    self.ma_half_time = ma_half_time

    log NewParameters(
            admin_fee=admin_fee,
            mid_fee=mid_fee,
            out_fee=out_fee,
            fee_gamma=fee_gamma,
            allowed_extra_profit=allowed_extra_profit,
            adjustment_step=adjustment_step,
            ma_half_time=ma_half_time
    )


@external
def revert_new_parameters():
    assert msg.sender == self.owner  # dev: only owner

    self.admin_actions_deadline = 0


@external
def commit_transfer_ownership(_owner: address):
    assert msg.sender == self.owner  # dev: only owner
    assert self.transfer_ownership_deadline == 0  # dev: active transfer

    _deadline: uint256 = block.timestamp + ADMIN_ACTIONS_DELAY
    self.transfer_ownership_deadline = _deadline
    self.future_owner = _owner

    log CommitNewAdmin(deadline=_deadline, admin=_owner)


@external
def apply_transfer_ownership():
    assert msg.sender == self.owner  # dev: only owner
    assert block.timestamp >= self.transfer_ownership_deadline  # dev: insufficient time
    assert self.transfer_ownership_deadline != 0  # dev: no active transfer

    self.transfer_ownership_deadline = 0
    _owner: address = self.future_owner
    self.owner = _owner

    log NewAdmin(admin=_owner)


@external
def revert_transfer_ownership():
    assert msg.sender == self.owner  # dev: only owner

    self.transfer_ownership_deadline = 0


@external
def kill_me():
    assert msg.sender == self.owner  # dev: only owner
    assert self.kill_deadline > block.timestamp  # dev: deadline has passed
    self.is_killed = True


@external
def unkill_me():
    assert msg.sender == self.owner  # dev: only owner
    self.is_killed = False


@external
def set_admin_fee_receiver(_admin_fee_receiver: address):
    assert msg.sender == self.owner  # dev: only owner
    self.admin_fee_receiver = _admin_fee_receiver
