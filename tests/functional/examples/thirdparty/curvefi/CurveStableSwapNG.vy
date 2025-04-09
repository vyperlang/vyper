# adapted from https://github.com/curvefi/stableswap-ng/blob/fd54b9a1a110d0e2e4f962583761d9e236b70967/contracts/main/CurveStableSwapNG.vy

# pragma enable-decimals
"""
@title CurveStableSwapNG
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice Stableswap implementation for up to 8 coins with no rehypothecation,
        i.e. the AMM does not deposit tokens into other contracts. The Pool contract also
        records exponential moving averages for coins relative to coin 0.
@dev Asset Types:
        0. Standard ERC20 token with no additional features.
                          Note: Users are advised to do careful due-diligence on
                                ERC20 tokens that they interact with, as this
                                contract cannot differentiate between harmless and
                                malicious ERC20 tokens.
        1. Oracle - token with rate oracle (e.g. wstETH)
                    Note: Oracles may be controlled externally by an EOA. Users
                          are advised to proceed with caution.
        2. Rebasing - token with rebase (e.g. stETH).
                      Note: Users and Integrators are advised to understand how
                            the AMM contract works with rebasing balances.
        3. ERC4626 - token with convertToAssets method (e.g. sDAI).
                     Note: Some ERC4626 implementations may be susceptible to
                           Donation/Inflation attacks. Users are advised to
                           proceed with caution.
     Supports:
        1. ERC20 support for return True/revert, return True/False, return None
        2. ERC20 tokens can have arbitrary decimals (<=18).
        3. ERC20 tokens that rebase (either positive or fee on transfer)
        4. ERC20 tokens that have a rate oracle (e.g. wstETH, cbETH, sDAI, etc.)
           Note: Oracle precision _must_ be 10**18.
        5. ERC4626 tokens with arbitrary precision (<=18) of Vault token and underlying
           asset.
     Additional features include:
        1. Adds price oracles based on AMM State Price (and _not_ last traded price).
        2. Adds TVL oracle based on D.
        3. `exchange_received`: swaps that expect an ERC20 transfer to have occurred
           prior to executing the swap.
           Note: a. If pool contains rebasing tokens and one of the `asset_types` is 2 (Rebasing)
                    then calling `exchange_received` will REVERT.
                 b. If pool contains rebasing token and `asset_types` does not contain 2 (Rebasing)
                    then this is an incorrect implementation and rebases can be
                    stolen.
        4. Adds `get_dx`: Similar to `get_dy` which returns an expected output
           of coin[j] for given `dx` amount of coin[i], `get_dx` returns expected
           input of coin[i] for an output amount of coin[j].
        5. Fees are dynamic: AMM will charge a higher fee if pool depegs. This can cause very
                             slight discrepancies between calculated fees and realised fees.
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from ethereum.ercs import IERC4626

implements: IERC20

# ------------------------------- Interfaces ---------------------------------

interface Factory:
    def fee_receiver() -> address: view
    def admin() -> address: view
    def views_implementation() -> address: view

interface IERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes32: view

interface StableSwapViews:
    def get_dx(i: int128, j: int128, dy: uint256, pool: address) -> uint256: view
    def get_dy(i: int128, j: int128, dx: uint256, pool: address) -> uint256: view
    def dynamic_fee(i: int128, j: int128, pool: address) -> uint256: view
    def calc_token_amount(
        _amounts: DynArray[uint256, MAX_COINS],
        _is_deposit: bool,
        _pool: address
    ) -> uint256: view

# --------------------------------- Events -----------------------------------

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

event TokenExchange:
    buyer: indexed(address)
    sold_id: uint128
    tokens_sold: uint256
    bought_id: uint128
    tokens_bought: uint256

event TokenExchangeUnderlying:
    buyer: indexed(address)
    sold_id: int128
    tokens_sold: uint256
    bought_id: int128
    tokens_bought: uint256

event AddLiquidity:
    provider: indexed(address)
    token_amounts: DynArray[uint256, MAX_COINS]
    fees: DynArray[uint256, MAX_COINS]
    invariant: uint256
    token_supply: uint256

event RemoveLiquidity:
    provider: indexed(address)
    token_amounts: DynArray[uint256, MAX_COINS]
    fees: DynArray[uint256, MAX_COINS]
    token_supply: uint256

event RemoveLiquidityOne:
    provider: indexed(address)
    token_id: uint128
    token_amount: uint256
    coin_amount: uint256
    token_supply: uint256

event RemoveLiquidityImbalance:
    provider: indexed(address)
    token_amounts: DynArray[uint256, MAX_COINS]
    fees: DynArray[uint256, MAX_COINS]
    invariant: uint256
    token_supply: uint256

event RampA:
    old_A: uint256
    new_A: uint256
    initial_time: uint256
    future_time: uint256

event StopRampA:
    A: uint256
    t: uint256

event ApplyNewFee:
    fee: uint256
    offpeg_fee_multiplier: uint256


MAX_COINS: constant(uint256) = 8  # max coins is 8 in the factory
MAX_COINS_128: constant(uint128) = 8

# ---------------------------- Pool Variables --------------------------------

N_COINS: public(immutable(uint256))
N_COINS_128: immutable(uint128)
PRECISION: constant(uint256) = 10 ** 18

factory: immutable(Factory)
coins: public(immutable(DynArray[address, MAX_COINS]))
asset_types: immutable(DynArray[uint8, MAX_COINS])
stored_balances: DynArray[uint256, MAX_COINS]

# Fee specific vars
FEE_DENOMINATOR: constant(uint256) = 10 ** 10
fee: public(uint256)  # fee * 1e10
offpeg_fee_multiplier: public(uint256)  # * 1e10
admin_fee: public(constant(uint256)) = 5000000000
MAX_FEE: constant(uint256) = 5 * 10 ** 9

# ---------------------- Pool Amplification Parameters -----------------------

A_PRECISION: constant(uint256) = 100
MAX_A: constant(uint256) = 10 ** 6
MAX_A_CHANGE: constant(uint256) = 10

initial_A: public(uint256)
future_A: public(uint256)
initial_A_time: public(uint256)
future_A_time: public(uint256)

# ---------------------------- Admin Variables -------------------------------

MIN_RAMP_TIME: constant(uint256) = 86400
admin_balances: public(DynArray[uint256, MAX_COINS])

# ----------------------- Oracle Specific vars -------------------------------

rate_multipliers: immutable(DynArray[uint256, MAX_COINS])
# [bytes4 method_id][bytes8 <empty>][bytes20 oracle]
oracles: DynArray[uint256, MAX_COINS]

# For ERC4626 tokens, we need:
call_amount: immutable(DynArray[uint256, MAX_COINS])
scale_factor: immutable(DynArray[uint256, MAX_COINS])

last_prices_packed: DynArray[uint256, MAX_COINS]  #  packing: last_price, ma_price
last_D_packed: uint256                            #  packing: last_D, ma_D
ma_exp_time: public(uint256)
D_ma_time: public(uint256)
ma_last_time: public(uint256)                     # packing: ma_last_time_p, ma_last_time_D
# ma_last_time has a distinction for p and D because p is _not_ updated if
# users remove_liquidity, but D is.

# shift(2**32 - 1, 224)
ORACLE_BIT_MASK: constant(uint256) = (2**32 - 1) * 256**28

# --------------------------- ERC20 Specific Vars ----------------------------

name: public(immutable(String[64]))
symbol: public(immutable(String[32]))
decimals: public(constant(uint8)) = 18
version: public(constant(String[8])) = "v7.0.0"

balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
total_supply: uint256
nonces: public(HashMap[address, uint256])

# keccak256("isValidSignature(bytes32,bytes)")[:4] << 224
ERC1271_MAGIC_VAL: constant(bytes32) = 0x1626ba7e00000000000000000000000000000000000000000000000000000000
EIP712_TYPEHASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract,bytes32 salt)")
EIP2612_TYPEHASH: constant(bytes32) = keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)")

VERSION_HASH: constant(bytes32) = keccak256(version)
NAME_HASH: immutable(bytes32)
CACHED_CHAIN_ID: immutable(uint256)
salt: public(immutable(bytes32))
CACHED_DOMAIN_SEPARATOR: immutable(bytes32)


# ------------------------------ AMM Setup -----------------------------------


#@foooo
@deploy
def __init__(
    _name: String[32],
    _symbol: String[10],
    _A: uint256,
    _fee: uint256,
    _offpeg_fee_multiplier: uint256,
    _ma_exp_time: uint256,
    _coins: DynArray[address, MAX_COINS],
    _rate_multipliers: DynArray[uint256, MAX_COINS],
    _asset_types: DynArray[uint8, MAX_COINS],
    _method_ids: DynArray[bytes4, MAX_COINS],
    _oracles: DynArray[address, MAX_COINS],
):
    """
    @notice Initialize the pool contract
    @param _name Name of the new plain pool.
    @param _symbol Symbol for the new plain pool.
    @param _A Amplification co-efficient - a lower value here means
              less tolerance for imbalance within the pool's assets.
              Suggested values include:
               * Uncollateralized algorithmic stablecoins: 5-10
               * Non-redeemable, collateralized assets: 100
               * Redeemable assets: 200-400
    @param _fee Trade fee, given as an integer with 1e10 precision. The
                the maximum is 1% (100000000).
                50% of the fee is distributed to veCRV holders.
    @param _offpeg_fee_multiplier A multiplier that determines how much to increase
                                  Fees by when assets in the AMM depeg. Example value: 20000000000
    @param _ma_exp_time Averaging window of oracle. Set as time_in_seconds // ln(2)
                        Example: for 10 minute EMA, _ma_exp_time is 600 // ln(2) ~= 866
    @param _coins List of addresses of the coins being used in the pool.
    @param _rate_multipliers An array of: [10 ** (36 - _coins[n].decimals()), ... for n in range(N_COINS)]
    @param _asset_types Array of uint8 representing tokens in pool
    @param _method_ids Array of first four bytes of the Keccak-256 hash of the function signatures
                       of the oracle addresses that gives rate oracles.
                       Calculated as: keccak(text=event_signature.replace(" ", ""))[:4]
    @param _oracles Array of rate oracle addresses.
    """

    coins = _coins
    asset_types = _asset_types
    __n_coins: uint256 = len(_coins)
    N_COINS = __n_coins
    N_COINS_128 = convert(__n_coins, uint128)

    rate_multipliers = _rate_multipliers

    factory = Factory(msg.sender)

    A: uint256 = _A * A_PRECISION
    self.initial_A = A
    self.future_A = A
    self.fee = _fee
    self.offpeg_fee_multiplier = _offpeg_fee_multiplier

    assert _ma_exp_time != 0
    self.ma_exp_time = _ma_exp_time
    self.D_ma_time = 62324  # <--------- 12 hours default on contract start.
    self.ma_last_time = self.pack_2(block.timestamp, block.timestamp)

    #  ------------------- initialize storage for DynArrays ------------------

    _call_amount: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    _scale_factor: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if i < N_COINS_128 - 1:
            self.last_prices_packed.append(self.pack_2(10**18, 10**18))

        self.oracles.append(convert(_method_ids[i], uint256) * 2**224 | convert(_oracles[i], uint256))
        self.stored_balances.append(0)
        self.admin_balances.append(0)

        if _asset_types[i] == 3:

            _call_amount.append(10**convert(staticcall IERC20Detailed(_coins[i]).decimals(), uint256))
            _underlying_asset: address = staticcall IERC4626(_coins[i]).asset()
            _scale_factor.append(10**(18 - convert(staticcall IERC20Detailed(_underlying_asset).decimals(), uint256)))

        else:

            _call_amount.append(0)
            _scale_factor.append(0)

    call_amount = _call_amount
    scale_factor = _scale_factor

    # ----------------------------- ERC20 stuff ------------------------------

    name = _name
    symbol = _symbol

    # EIP712 related params -----------------
    NAME_HASH = keccak256(name)
    salt = block.prevhash
    CACHED_CHAIN_ID = chain.id
    CACHED_DOMAIN_SEPARATOR = keccak256(
        abi_encode(
            EIP712_TYPEHASH,
            NAME_HASH,
            VERSION_HASH,
            chain.id,
            self,
            salt,
        )
    )

    # ------------------------ Fire a transfer event -------------------------

    log Transfer(sender=empty(address), receiver=msg.sender, value=0)


# ------------------ Token transfers in and out of the AMM -------------------


@internal
def _transfer_in(
    coin_idx: uint128,
    dx: uint256,
    sender: address,
    expect_optimistic_transfer: bool,
) -> uint256:
    """
    @notice Contains all logic to handle ERC20 token transfers.
    @param coin_idx Index of the coin to transfer in.
    @param dx amount of `_coin` to transfer into the pool.
    @param dy amount of `_coin` to transfer out of the pool.
    @param sender address to transfer `_coin` from.
    @param receiver address to transfer `_coin` to.
    @param expect_optimistic_transfer True if contract expects an optimistic coin transfer
    """
    _dx: uint256 = staticcall IERC20(coins[coin_idx]).balanceOf(self)

    # ------------------------- Handle Transfers -----------------------------

    if expect_optimistic_transfer:

        _dx = _dx - self.stored_balances[coin_idx]
        assert _dx >= dx

    else:

        assert dx > 0  # dev : do not transferFrom 0 tokens into the pool
        assert extcall IERC20(coins[coin_idx]).transferFrom(
            sender, self, dx, default_return_value=True
        )

        _dx = staticcall IERC20(coins[coin_idx]).balanceOf(self) - _dx

    # --------------------------- Store transferred in amount ---------------------------

    self.stored_balances[coin_idx] += _dx

    return _dx


@internal
def _transfer_out(_coin_idx: uint128, _amount: uint256, receiver: address):
    """
    @notice Transfer a single token from the pool to receiver.
    @dev This function is called by `remove_liquidity` and
         `remove_liquidity_one`, `_exchange` and `_withdraw_admin_fees` methods.
    @param _coin_idx Index of the token to transfer out
    @param _amount Amount of token to transfer out
    @param receiver Address to send the tokens to
    """

    coin_balance: uint256 = staticcall IERC20(coins[_coin_idx]).balanceOf(self)

    # ------------------------- Handle Transfers -----------------------------

    assert extcall IERC20(coins[_coin_idx]).transfer(
        receiver, _amount, default_return_value=True
    )

    # ----------------------- Update Stored Balances -------------------------

    self.stored_balances[_coin_idx] = coin_balance - _amount


# -------------------------- AMM Special Methods -----------------------------


@view
@internal
def _stored_rates() -> DynArray[uint256, MAX_COINS]:
    """
    @notice Gets rate multipliers for each coin.
    @dev If the coin has a rate oracle that has been properly initialised,
         this method queries that rate by static-calling an external
         contract.
    """
    rates: DynArray[uint256, MAX_COINS] = rate_multipliers
    oracles: DynArray[uint256, MAX_COINS] = self.oracles

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if asset_types[i] == 1 and not oracles[i] == 0:

            # NOTE: fetched_rate is assumed to be 10**18 precision
            fetched_rate: uint256 = convert(
                raw_call(
                    convert(oracles[i] % 2**160, address),
                    abi_encode(oracles[i] & ORACLE_BIT_MASK),
                    max_outsize=32,
                    is_static_call=True,
                ),
                uint256
            )

            rates[i] = unsafe_div(rates[i] * fetched_rate, PRECISION)

        elif asset_types[i] == 3:  # ERC4626

            # fetched_rate: uint256 = ERC4626(coins[i]).convertToAssets(call_amount[i]) * scale_factor[i]
            # here: call_amount has ERC4626 precision, but the returned value is scaled up to 18
            # using scale_factor which is (18 - n) if underlying asset has n decimals.
            rates[i] = unsafe_div(
                rates[i] * (staticcall IERC4626(coins[i]).convertToAssets(call_amount[i])) * scale_factor[i],
                PRECISION
            )  # 1e18 precision

    return rates


@view
@internal
def _balances() -> DynArray[uint256, MAX_COINS]:
    """
    @notice Calculates the pool's balances _excluding_ the admin's balances.
    @dev If the pool contains rebasing tokens, this method ensures LPs keep all
            rebases and admin only claims swap fees. This also means that, since
            admin's balances are stored in an array and not inferred from read balances,
            the fees in the rebasing token that the admin collects is immune to
            slashing events.
    """
    result: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances_i: uint256 = 0

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if 2 in asset_types:
            balances_i = staticcall IERC20(coins[i]).balanceOf(self) - self.admin_balances[i]
        else:
            balances_i = self.stored_balances[i] - self.admin_balances[i]

        result.append(balances_i)

    return result


# -------------------------- AMM Main Functions ------------------------------


@external
@nonreentrant
def exchange(
    i: uint128,
    j: uint128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index value of the coin to recieve
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @return Actual amount of `j` received
    """
    return self._exchange(
        msg.sender,
        i,
        j,
        _dx,
        _min_dy,
        _receiver,
        False
    )


@external
@nonreentrant
def exchange_received(
    i: uint128,
    j: uint128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins without transferring token in
    @dev The contract swaps tokens based on a change in balance of coin[i]. The
         dx = ERC20(coin[i]).balanceOf(self) - self.stored_balances[i]. Users of
         this method are dex aggregators, arbitrageurs, or other users who do not
         wish to grant approvals to the contract: they would instead send tokens
         directly to the contract and call `exchange_received`.
         Note: This is disabled if pool contains rebasing tokens.
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @return Actual amount of `j` received
    """
    assert not 2 in asset_types  # dev: exchange_received not supported if pool contains rebasing tokens
    return self._exchange(
        msg.sender,
        i,
        j,
        _dx,
        _min_dy,
        _receiver,
        True,  # <--------------------------------------- swap optimistically.
    )


@external
@nonreentrant
def add_liquidity(
    _amounts: DynArray[uint256, MAX_COINS],
    _min_mint_amount: uint256,
    _receiver: address = msg.sender
) -> uint256:
    """
    @notice Deposit coins into the pool
    @param _amounts List of amounts of coins to deposit
    @param _min_mint_amount Minimum amount of LP tokens to mint from the deposit
    @param _receiver Address that owns the minted LP tokens
    @return Amount of LP tokens received by depositing
    """
    amp: uint256 = self._A()
    old_balances: DynArray[uint256, MAX_COINS] = self._balances()
    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()

    # Initial invariant
    D0: uint256 = self.get_D_mem(rates, old_balances, amp)

    total_supply: uint256 = self.total_supply
    new_balances: DynArray[uint256, MAX_COINS] = old_balances

    # -------------------------- Do Transfers In -----------------------------

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if _amounts[i] > 0:

            new_balances[i] += self._transfer_in(
                i,
                _amounts[i],
                msg.sender,
                False,  # expect_optimistic_transfer
            )

        else:

            assert total_supply != 0  # dev: initial deposit requires all coins

    # ------------------------------------------------------------------------

    # Invariant after change
    D1: uint256 = self.get_D_mem(rates, new_balances, amp)
    assert D1 > D0

    # We need to recalculate the invariant accounting for fees
    # to calculate fair user's share
    fees: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    mint_amount: uint256 = 0

    if total_supply > 0:

        ideal_balance: uint256 = 0
        difference: uint256 = 0
        new_balance: uint256 = 0

        ys: uint256 = (D0 + D1) // N_COINS
        xs: uint256 = 0
        _dynamic_fee_i: uint256 = 0

        # Only account for fees if we are not the first to deposit
        base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))

        for i: uint128 in range(MAX_COINS_128):

            if i == N_COINS_128:
                break

            ideal_balance = D1 * old_balances[i] // D0
            difference = 0
            new_balance = new_balances[i]

            if ideal_balance > new_balance:
                difference = ideal_balance - new_balance
            else:
                difference = new_balance - ideal_balance

            # fee[i] = _dynamic_fee(i, j) * difference // FEE_DENOMINATOR
            xs = unsafe_div(rates[i] * (old_balances[i] + new_balance), PRECISION)
            _dynamic_fee_i = self._dynamic_fee(xs, ys, base_fee)
            fees.append(_dynamic_fee_i * difference // FEE_DENOMINATOR)
            self.admin_balances[i] += fees[i] * admin_fee // FEE_DENOMINATOR
            new_balances[i] -= fees[i]

        xp: DynArray[uint256, MAX_COINS] = self._xp_mem(rates, new_balances)
        D1 = self.get_D(xp, amp)  # <--------------- Reuse D1 for new D value.
        mint_amount = total_supply * (D1 - D0) // D0
        self.upkeep_oracles(xp, amp, D1)

    else:

        mint_amount = D1  # Take the dust if there was any

        # (re)instantiate D oracle if totalSupply is zero.
        self.last_D_packed = self.pack_2(D1, D1)

    assert mint_amount >= _min_mint_amount, "Slippage screwed you"

    # Mint pool tokens
    total_supply += mint_amount
    self.balanceOf[_receiver] += mint_amount
    self.total_supply = total_supply
    log Transfer(sender=empty(address), receiver=_receiver, value=mint_amount)

    log AddLiquidity(provider=msg.sender, token_amounts=_amounts, fees=fees, invariant=D1, token_supply=total_supply)

    return mint_amount


@external
@nonreentrant
def remove_liquidity_one_coin(
    _burn_amount: uint256,
    i: uint128,
    _min_received: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Withdraw a single coin from the pool
    @param _burn_amount Amount of LP tokens to burn in the withdrawal
    @param i Index value of the coin to withdraw
    @param _min_received Minimum amount of coin to receive
    @param _receiver Address that receives the withdrawn coins
    @return Amount of coin received
    """
    assert _burn_amount > 0  # dev: do not remove 0 LP tokens
    dy: uint256 = 0
    fee: uint256 = 0
    xp: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    amp: uint256 = empty(uint256)
    D: uint256 = empty(uint256)

    dy, fee, xp, amp, D = self._calc_withdraw_one_coin(_burn_amount, i)
    assert dy >= _min_received, "Not enough coins removed"

    self.admin_balances[i] += fee * admin_fee // FEE_DENOMINATOR

    self._burnFrom(msg.sender, _burn_amount)

    self._transfer_out(i, dy, _receiver)

    log RemoveLiquidityOne(provider=msg.sender, token_id=i, token_amount=_burn_amount, coin_amount=dy, token_supply=self.total_supply)

    self.upkeep_oracles(xp, amp, D)

    return dy


@external
@nonreentrant
def remove_liquidity_imbalance(
    _amounts: DynArray[uint256, MAX_COINS],
    _max_burn_amount: uint256,
    _receiver: address = msg.sender
) -> uint256:
    """
    @notice Withdraw coins from the pool in an imbalanced amount
    @param _amounts List of amounts of underlying coins to withdraw
    @param _max_burn_amount Maximum amount of LP token to burn in the withdrawal
    @param _receiver Address that receives the withdrawn coins
    @return Actual amount of the LP token burned in the withdrawal
    """
    amp: uint256 = self._A()
    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    old_balances: DynArray[uint256, MAX_COINS] = self._balances()
    D0: uint256 = self.get_D_mem(rates, old_balances, amp)
    new_balances: DynArray[uint256, MAX_COINS] = old_balances

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if _amounts[i] != 0:
            new_balances[i] -= _amounts[i]
            self._transfer_out(i, _amounts[i], _receiver)

    D1: uint256 = self.get_D_mem(rates, new_balances, amp)
    base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
    ys: uint256 = (D0 + D1) // N_COINS

    fees: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    dynamic_fee: uint256 = 0
    xs: uint256 = 0
    ideal_balance: uint256 = 0
    difference: uint256 = 0
    new_balance: uint256 = 0

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        ideal_balance = D1 * old_balances[i] // D0
        difference = 0
        new_balance = new_balances[i]

        if ideal_balance > new_balance:
            difference = ideal_balance - new_balance
        else:
            difference = new_balance - ideal_balance

        xs = unsafe_div(rates[i] * (old_balances[i] + new_balance), PRECISION)
        dynamic_fee = self._dynamic_fee(xs, ys, base_fee)
        fees.append(dynamic_fee * difference // FEE_DENOMINATOR)

        self.admin_balances[i] += fees[i] * admin_fee // FEE_DENOMINATOR
        new_balances[i] -= fees[i]

    D1 = self.get_D_mem(rates, new_balances, amp)  # dev: reuse D1 for new D.

    self.upkeep_oracles(new_balances, amp, D1)

    total_supply: uint256 = self.total_supply
    burn_amount: uint256 = ((D0 - D1) * total_supply // D0) + 1
    assert burn_amount > 1  # dev: zero tokens burned
    assert burn_amount <= _max_burn_amount, "Slippage screwed you"

    total_supply -= burn_amount
    self._burnFrom(msg.sender, burn_amount)

    log RemoveLiquidityImbalance(provider=msg.sender, token_amounts=_amounts, fees=fees, invariant=D1, token_supply=total_supply)


    return burn_amount


@external
@nonreentrant
def remove_liquidity(
    _burn_amount: uint256,
    _min_amounts: DynArray[uint256, MAX_COINS],
    _receiver: address = msg.sender,
    _claim_admin_fees: bool = True,
) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Withdraw coins from the pool
    @dev Withdrawal amounts are based on current deposit ratios
    @param _burn_amount Quantity of LP tokens to burn in the withdrawal
    @param _min_amounts Minimum amounts of underlying coins to receive
    @param _receiver Address that receives the withdrawn coins
    @return List of amounts of coins that were withdrawn
    """
    total_supply: uint256 = self.total_supply
    assert _burn_amount > 0  # dev: invalid burn amount

    amounts: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = self._balances()

    value: uint256 = 0
    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        value = balances[i] * _burn_amount // total_supply
        assert value >= _min_amounts[i], "Withdrawal resulted in fewer coins than expected"
        amounts.append(value)
        self._transfer_out(i, value, _receiver)

    self._burnFrom(msg.sender, _burn_amount)  # <---- Updates self.total_supply

    # --------------------------- Upkeep D_oracle ----------------------------

    ma_last_time_unpacked: uint256[2] = self.unpack_2(self.ma_last_time)
    last_D_packed_current: uint256 = self.last_D_packed
    old_D: uint256 = last_D_packed_current & (2**128 - 1)

    self.last_D_packed = self.pack_2(
        old_D - unsafe_div(old_D * _burn_amount, total_supply),  # new_D = proportionally reduce D.
        self._calc_moving_average(
            last_D_packed_current,
            self.D_ma_time,
            ma_last_time_unpacked[1]
        )
    )

    if ma_last_time_unpacked[1] < block.timestamp:
        ma_last_time_unpacked[1] = block.timestamp

    self.ma_last_time = self.pack_2(ma_last_time_unpacked[0], ma_last_time_unpacked[1])

    # ------------------------------- Log event ------------------------------

    log RemoveLiquidity(
        provider=msg.sender,
        token_amounts=amounts,
        fees=empty(DynArray[uint256, MAX_COINS]),
        token_supply=total_supply - _burn_amount
    )

    # ------- Withdraw admin fees if _claim_admin_fees is set to True --------
    if _claim_admin_fees:
        self._withdraw_admin_fees()

    return amounts


@external
def withdraw_admin_fees():
    """
    @notice Claim admin fees. Callable by anyone.
    """
    self._withdraw_admin_fees()


# ------------------------ AMM Internal Functions ----------------------------


@view
@internal
def _dynamic_fee(xpi: uint256, xpj: uint256, _fee: uint256) -> uint256:

    _offpeg_fee_multiplier: uint256 = self.offpeg_fee_multiplier
    if _offpeg_fee_multiplier <= FEE_DENOMINATOR:
        return _fee

    xps2: uint256 = (xpi + xpj) ** 2
    return (
        (_offpeg_fee_multiplier * _fee) //
        ((_offpeg_fee_multiplier - FEE_DENOMINATOR) * 4 * xpi * xpj // xps2 + FEE_DENOMINATOR)
    )


@internal
def __exchange(
    x: uint256,
    _xp: DynArray[uint256, MAX_COINS],
    rates: DynArray[uint256, MAX_COINS],
    i: uint128,
    j: uint128,
) -> uint256:

    amp: uint256 = self._A()
    D: uint256 = self.get_D(_xp, amp)
    y: uint256 = self.get_y(i, j, x, _xp, amp, D)

    dy: uint256 = _xp[j] - y - 1  # -1 just in case there were some rounding errors
    dy_fee: uint256 = dy * self._dynamic_fee((_xp[i] + x) // 2, (_xp[j] + y) // 2, self.fee) // FEE_DENOMINATOR

    # Convert all to real units
    dy = (dy - dy_fee) * PRECISION // rates[j]

    self.admin_balances[j] += (
        dy_fee * admin_fee // FEE_DENOMINATOR
    ) * PRECISION // rates[j]

    # Calculate and store state prices:
    xp: DynArray[uint256, MAX_COINS] = _xp
    xp[i] = x
    xp[j] = y
    # D is not changed because we did not apply a fee
    self.upkeep_oracles(xp, amp, D)

    return dy


@internal
def _exchange(
    sender: address,
    i: uint128,
    j: uint128,
    _dx: uint256,
    _min_dy: uint256,
    receiver: address,
    expect_optimistic_transfer: bool
) -> uint256:

    assert i != j  # dev: coin index out of range
    assert _dx > 0  # dev: do not exchange 0 coins

    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    old_balances: DynArray[uint256, MAX_COINS] = self._balances()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(rates, old_balances)

    # --------------------------- Do Transfer in -----------------------------

    # `dx` is whatever the pool received after ERC20 transfer:
    dx: uint256 = self._transfer_in(
        i,
        _dx,
        sender,
        expect_optimistic_transfer
    )

    # ------------------------------- Exchange -------------------------------

    x: uint256 = xp[i] + dx * rates[i] // PRECISION
    dy: uint256 = self.__exchange(x, xp, rates, i, j)
    assert dy >= _min_dy, "Exchange resulted in fewer coins than expected"

    # --------------------------- Do Transfer out ----------------------------

    self._transfer_out(j, dy, receiver)

    # ------------------------------------------------------------------------

    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=_dx, bought_id=j, tokens_bought=dy)

    return dy


@internal
def _withdraw_admin_fees():
    fee_receiver: address = staticcall factory.fee_receiver()
    assert fee_receiver != empty(address)  # dev: fee receiver not set

    admin_balances: DynArray[uint256, MAX_COINS] = self.admin_balances
    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        if admin_balances[i] > 0:

            self._transfer_out(i, admin_balances[i], fee_receiver)
            admin_balances[i] = 0

    self.admin_balances = admin_balances


# --------------------------- AMM Math Functions -----------------------------


@view
@internal
def get_y(
    i: uint128,
    j: uint128,
    x: uint256,
    xp: DynArray[uint256, MAX_COINS],
    _amp: uint256,
    _D: uint256
) -> uint256:
    """
    Calculate x[j] if one makes x[i] = x

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price/precision

    assert i != j       # dev: same coin
    assert j >= 0       # dev: j below zero
    assert j < N_COINS_128  # dev: j above N_COINS

    # should be unreachable, but good for safety
    assert i >= 0
    assert i < N_COINS_128

    amp: uint256 = _amp
    D: uint256 = _D

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = amp * N_COINS

    for _i: uint128 in range(MAX_COINS_128):

        if _i == N_COINS_128:
            break

        if _i == i:
            _x = x
        elif _i != j:
            _x = xp[_i]
        else:
            continue

        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_PRECISION // (Ann * N_COINS)
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


@view
@internal
def get_D(_xp: DynArray[uint256, MAX_COINS], _amp: uint256) -> uint256:
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
    Ann: uint256 = _amp * N_COINS
    D_P: uint256 = 0
    Dprev: uint256 = 0

    for i: uint256 in range(255):

        D_P = D
        for x: uint256 in _xp:
            D_P = D_P * D // (x * N_COINS)
        Dprev = D

        # (Ann * S // A_PRECISION + D_P * N_COINS) * D // ((Ann - A_PRECISION) * D // A_PRECISION + (N_COINS + 1) * D_P)
        D = (
            (unsafe_div(Ann * S, A_PRECISION) + D_P * N_COINS) *
            D // (
                unsafe_div((Ann - A_PRECISION) * D, A_PRECISION) +
                unsafe_add(N_COINS, 1) * D_P
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


@view
@internal
def get_y_D(
    A: uint256,
    i: uint128,
    xp: DynArray[uint256, MAX_COINS],
    D: uint256
) -> uint256:
    """
    Calculate x[i] if one reduces D from being calculated for xp to D

    Done by solving quadratic equation iteratively.
    x_1**2 + x_1 * (sum' - (A*n**n - 1) * D // (A * n**n)) = D ** (n + 1) // (n ** (2 * n) * prod' * A)
    x_1**2 + b*x_1 = c

    x_1 = (x_1**2 + c) // (2*x_1 + b)
    """
    # x in the input is converted to the same price/precision

    assert i >= 0  # dev: i below zero
    assert i < N_COINS_128  # dev: i above N_COINS

    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = A * N_COINS

    for _i: uint128 in range(MAX_COINS_128):

        if _i == N_COINS_128:
            break

        if _i != i:
            _x = xp[_i]
        else:
            continue
        S_ += _x
        c = c * D // (_x * N_COINS)

    c = c * D * A_PRECISION // (Ann * N_COINS)
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


@view
@internal
def _A() -> uint256:
    """
    Handle ramping A up or down
    """
    t1: uint256 = self.future_A_time
    A1: uint256 = self.future_A

    if block.timestamp < t1:
        A0: uint256 = self.initial_A
        t0: uint256 = self.initial_A_time
        # Expressions in uint256 cannot have negative numbers, thus "if"
        if A1 > A0:
            return A0 + (A1 - A0) * (block.timestamp - t0) // (t1 - t0)
        else:
            return A0 - (A0 - A1) * (block.timestamp - t0) // (t1 - t0)

    else:  # when t1 == 0 or block.timestamp >= t1
        return A1


@view
@internal
def _xp_mem(
    _rates: DynArray[uint256, MAX_COINS],
    _balances: DynArray[uint256, MAX_COINS]
) -> DynArray[uint256, MAX_COINS]:

    result: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint128 in range(MAX_COINS_128):
        if i == N_COINS_128:
            break
        result.append(_rates[i] * _balances[i] // PRECISION)
    return result


@view
@internal
def get_D_mem(
    _rates: DynArray[uint256, MAX_COINS],
    _balances: DynArray[uint256, MAX_COINS],
    _amp: uint256
) -> uint256:
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(_rates, _balances)
    return self.get_D(xp, _amp)


@view
@internal
def _calc_withdraw_one_coin(
    _burn_amount: uint256,
    i: uint128
) -> (
    uint256,
    uint256,
    DynArray[uint256, MAX_COINS],
    uint256,
    uint256
):
    # First, need to calculate
    # * Get current D
    # * Solve Eqn against y_i for D - _token_amount
    amp: uint256 = self._A()
    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(rates, self._balances())
    D0: uint256 = self.get_D(xp, amp)

    total_supply: uint256 = self.total_supply
    D1: uint256 = D0 - _burn_amount * D0 // total_supply
    new_y: uint256 = self.get_y_D(amp, i, xp, D1)

    base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
    ys: uint256 = (D0 + D1) // (2 * N_COINS)
    xp_reduced: DynArray[uint256, MAX_COINS] = xp

    dx_expected: uint256 = 0
    xp_j: uint256 = 0
    xavg: uint256 = 0
    dynamic_fee: uint256 = 0

    for j: uint128 in range(MAX_COINS_128):

        if j == N_COINS_128:
            break

        dx_expected = 0
        xp_j = xp[j]

        if j == i:
            dx_expected = xp_j * D1 // D0 - new_y
            xavg = (xp_j + new_y) // 2
        else:
            dx_expected = xp_j - xp_j * D1 // D0
            xavg = xp_j

        dynamic_fee = self._dynamic_fee(xavg, ys, base_fee)
        xp_reduced[j] = xp_j - dynamic_fee * dx_expected // FEE_DENOMINATOR

    dy: uint256 = xp_reduced[i] - self.get_y_D(amp, i, xp_reduced, D1)
    dy_0: uint256 = (xp[i] - new_y) * PRECISION // rates[i]  # w/o fees
    dy = (dy - 1) * PRECISION // rates[i]  # Withdraw less to account for rounding errors

    # update xp with new_y for p calculations.
    xp[i] = new_y

    return dy, dy_0 - dy, xp, amp, D1


# -------------------------- AMM Price Methods -------------------------------

@pure
@internal
def pack_2(p1: uint256, p2: uint256) -> uint256:
    assert p1 < 2**128
    assert p2 < 2**128
    return p1 | (p2 << 128)


@pure
@internal
def unpack_2(packed: uint256) -> uint256[2]:
    return [packed & (2**128 - 1), packed >> 128]


@internal
@view
def _get_p(
    xp: DynArray[uint256, MAX_COINS],
    amp: uint256,
    D: uint256,
) -> DynArray[uint256, MAX_COINS]:

    # dx_0 // dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(amp, N_COINS)
    Dr: uint256 = unsafe_div(D, pow_mod256(N_COINS, N_COINS))

    for i: uint128 in range(MAX_COINS_128):

        if i == N_COINS_128:
            break

        Dr = Dr * D // xp[i]

    p: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp0_A: uint256 = ANN * xp[0] // A_PRECISION

    for i: uint256 in range(1, MAX_COINS):

        if i == N_COINS:
            break

        p.append(10**18 * (xp0_A + Dr * xp[0] // xp[i]) // (xp0_A + Dr))

    return p


@internal
def upkeep_oracles(xp: DynArray[uint256, MAX_COINS], amp: uint256, D: uint256):
    """
    @notice Upkeeps price and D oracles.
    """
    ma_last_time_unpacked: uint256[2] = self.unpack_2(self.ma_last_time)
    last_prices_packed_current: DynArray[uint256, MAX_COINS] = self.last_prices_packed
    last_prices_packed_new: DynArray[uint256, MAX_COINS] = last_prices_packed_current

    spot_price: DynArray[uint256, MAX_COINS] = self._get_p(xp, amp, D)

    # -------------------------- Upkeep price oracle -------------------------

    for i: uint256 in range(MAX_COINS):

        if i == N_COINS - 1:
            break

        if spot_price[i] != 0:

            # Upate packed prices -----------------
            last_prices_packed_new[i] = self.pack_2(
                spot_price[i],
                self._calc_moving_average(
                    last_prices_packed_current[i],
                    self.ma_exp_time,
                    ma_last_time_unpacked[0],  # index 0 is ma_exp_time for prices
                )
            )

    self.last_prices_packed = last_prices_packed_new

    # ---------------------------- Upkeep D oracle ---------------------------

    last_D_packed_current: uint256 = self.last_D_packed
    self.last_D_packed = self.pack_2(
        D,
        self._calc_moving_average(
            last_D_packed_current,
            self.D_ma_time,
            ma_last_time_unpacked[1],  # index 1 is ma_exp_time for D
        )
    )

    # Housekeeping: Update ma_last_time for p and D oracles ------------------
    for i: uint256 in range(2):
        if ma_last_time_unpacked[i] < block.timestamp:
            ma_last_time_unpacked[i] = block.timestamp

    self.ma_last_time = self.pack_2(ma_last_time_unpacked[0], ma_last_time_unpacked[1])


@internal
@view
def _calc_moving_average(
    packed_value: uint256,
    averaging_window: uint256,
    ma_last_time: uint256
) -> uint256:

    last_spot_value: uint256 = packed_value & (2**128 - 1)
    last_ema_value: uint256 = (packed_value >> 128)

    if ma_last_time < block.timestamp:  # calculate new_ema_value and return that.
        alpha: uint256 = self.exp(
            -convert(
                (block.timestamp - ma_last_time) * 10**18 // averaging_window, int256
            )
        )
        return (last_spot_value * (10**18 - alpha) + last_ema_value * alpha) // 10**18

    return last_ema_value


@view
@external
def last_price(i: uint256) -> uint256:
    return self.last_prices_packed[i] & (2**128 - 1)


@view
@external
def ema_price(i: uint256) -> uint256:
    return (self.last_prices_packed[i] >> 128)


@external
@view
def get_p(i: uint256) -> uint256:
    """
    @notice Returns the AMM State price of token
    @dev if i = 0, it will return the state price of coin[1].
    @param i index of state price (0 for coin[1], 1 for coin[2], ...)
    @return uint256 The state price quoted by the AMM for coin[i+1]
    """
    amp: uint256 = self._A()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(
        self._stored_rates(), self._balances()
    )
    D: uint256 = self.get_D(xp, amp)
    return self._get_p(xp, amp, D)[i]


@external
@view
@nonreentrant
def price_oracle(i: uint256) -> uint256:
    return self._calc_moving_average(
        self.last_prices_packed[i],
        self.ma_exp_time,
        self.ma_last_time & (2**128 - 1)
    )


@external
@view
@nonreentrant
def D_oracle() -> uint256:
    return self._calc_moving_average(
        self.last_D_packed,
        self.D_ma_time,
        self.ma_last_time >> 128
    )


# ----------------------------- Math Utils -----------------------------------


@internal
@pure
def exp(x: int256) -> uint256:
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
        return 0

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


# ---------------------------- ERC20 Utils -----------------------------------

@view
@internal
def _domain_separator() -> bytes32:
    if chain.id != CACHED_CHAIN_ID:
        return keccak256(
            abi_encode(
                EIP712_TYPEHASH,
                NAME_HASH,
                VERSION_HASH,
                chain.id,
                self,
                salt,
            )
        )
    return CACHED_DOMAIN_SEPARATOR


@internal
def _transfer(_from: address, _to: address, _value: uint256):
    # # NOTE: vyper does not allow underflows
    # #       so the following subtraction would revert on insufficient balance
    self.balanceOf[_from] -= _value
    self.balanceOf[_to] += _value

    log Transfer(sender=_from, receiver=_to, value=_value)



@internal
def _burnFrom(_from: address, _burn_amount: uint256):

    self.total_supply -= _burn_amount
    self.balanceOf[_from] -= _burn_amount
    log Transfer(sender=_from, receiver=empty(address), value=_burn_amount)


@external
def transfer(_to : address, _value : uint256) -> bool:
    """
    @dev Transfer token for a specified address
    @param _to The address to transfer to.
    @param _value The amount to be transferred.
    """
    self._transfer(msg.sender, _to, _value)
    return True


@external
def transferFrom(_from : address, _to : address, _value : uint256) -> bool:
    """
     @dev Transfer tokens from one address to another.
     @param _from address The address which you want to send tokens from
     @param _to address The address which you want to transfer to
     @param _value uint256 the amount of tokens to be transferred
    """
    self._transfer(_from, _to, _value)

    _allowance: uint256 = self.allowance[_from][msg.sender]
    if _allowance != max_value(uint256):
        self.allowance[_from][msg.sender] = _allowance - _value

    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    """
    @notice Approve the passed address to transfer the specified amount of
            tokens on behalf of msg.sender
    @dev Beware that changing an allowance via this method brings the risk that
         someone may use both the old and new allowance by unfortunate transaction
         ordering: https://github.com/ethereum/EIPs/issues/20#issuecomment-263524729
    @param _spender The address which will transfer the funds
    @param _value The amount of tokens that may be transferred
    @return bool success
    """
    self.allowance[msg.sender][_spender] = _value

    log Approval(owner=msg.sender, spender=_spender, value=_value)
    return True


@external
def permit(
    _owner: address,
    _spender: address,
    _value: uint256,
    _deadline: uint256,
    _v: uint8,
    _r: bytes32,
    _s: bytes32
) -> bool:
    """
    @notice Approves spender by owner's signature to expend owner's tokens.
        See https://eips.ethereum.org/EIPS/eip-2612.
    @dev Inspired by https://github.com/yearn/yearn-vaults/blob/main/contracts/Vault.vy#L753-L793
    @dev Supports smart contract wallets which implement ERC1271
        https://eips.ethereum.org/EIPS/eip-1271
    @param _owner The address which is a source of funds and has signed the Permit.
    @param _spender The address which is allowed to spend the funds.
    @param _value The amount of tokens to be spent.
    @param _deadline The timestamp after which the Permit is no longer valid.
    @param _v The bytes[64] of the valid secp256k1 signature of permit by owner
    @param _r The bytes[0:32] of the valid secp256k1 signature of permit by owner
    @param _s The bytes[32:64] of the valid secp256k1 signature of permit by owner
    @return True, if transaction completes successfully
    """
    assert _owner != empty(address)
    assert block.timestamp <= _deadline

    nonce: uint256 = self.nonces[_owner]
    digest: bytes32 = keccak256(
        concat(
            b"\x19\x01",
            self._domain_separator(),
            keccak256(abi_encode(EIP2612_TYPEHASH, _owner, _spender, _value, nonce, _deadline))
        )
    )

    if _owner.is_contract:
        sig: Bytes[65] = concat(abi_encode(_r, _s), slice(convert(_v, bytes32), 31, 1))
        # reentrancy not a concern since this is a staticcall
        assert staticcall IERC1271(_owner).isValidSignature(digest, sig) == ERC1271_MAGIC_VAL
    else:
        assert ecrecover(digest, convert(_v, uint256), convert(_r, uint256), convert(_s, uint256)) == _owner

    self.allowance[_owner][_spender] = _value
    self.nonces[_owner] = nonce + 1

    log Approval(owner=_owner, spender=_spender, value=_value)
    return True


@view
@external
def DOMAIN_SEPARATOR() -> bytes32:
    """
    @notice EIP712 domain separator.
    @return bytes32 Domain Separator set for the current chain.
    """
    return self._domain_separator()


# ------------------------- AMM View Functions -------------------------------


@view
@external
def get_dx(i: int128, j: int128, dy: uint256) -> uint256:
    """
    @notice Calculate the current input dx given output dy
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param dy Amount of `j` being received after exchange
    @return Amount of `i` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dx(i, j, dy, self)


@view
@external
def get_dy(i: int128, j: int128, dx: uint256) -> uint256:
    """
    @notice Calculate the current output dy given input dx
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param dx Amount of `i` being exchanged
    @return Amount of `j` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dy(i, j, dx, self)


@view
@external
def calc_withdraw_one_coin(_burn_amount: uint256, i: uint128) -> uint256:
    """
    @notice Calculate the amount received when withdrawing a single coin
    @param _burn_amount Amount of LP tokens to burn in the withdrawal
    @param i Index value of the coin to withdraw
    @return Amount of coin received
    """
    return self._calc_withdraw_one_coin(_burn_amount, i)[0]


@view
@external
@nonreentrant
def totalSupply() -> uint256:
    """
    @notice The total supply of pool LP tokens
    @return self.total_supply, 18 decimals.
    """
    return self.total_supply


@view
@external
@nonreentrant
def get_virtual_price() -> uint256:
    """
    @notice The current virtual price of the pool LP token
    @dev Useful for calculating profits.
         The method may be vulnerable to donation-style attacks if implementation
         contains rebasing tokens. For integrators, caution is advised.
    @return LP token virtual price normalized to 1e18
    """
    amp: uint256 = self._A()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(
        self._stored_rates(), self._balances()
    )
    D: uint256 = self.get_D(xp, amp)
    # D is in the units similar to DAI (e.g. converted to precision 1e18)
    # When balanced, D = n * x_u - total virtual value of the portfolio
    return D * PRECISION // self.total_supply


@view
@external
def calc_token_amount(
    _amounts: DynArray[uint256, MAX_COINS],
    _is_deposit: bool
) -> uint256:
    """
    @notice Calculate addition or reduction in token supply from a deposit or withdrawal
    @param _amounts Amount of each coin being deposited
    @param _is_deposit set True for deposits, False for withdrawals
    @return Expected amount of LP tokens received
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).calc_token_amount(_amounts, _is_deposit, self)


@view
@external
def A() -> uint256:
    return self._A() // A_PRECISION


@view
@external
def A_precise() -> uint256:
    return self._A()


@view
@external
def balances(i: uint256) -> uint256:
    """
    @notice Get the current balance of a coin within the
            pool, less the accrued admin fees
    @param i Index value for the coin to query balance of
    @return Token balance
    """
    return self._balances()[i]


@view
@external
def get_balances() -> DynArray[uint256, MAX_COINS]:
    return self._balances()


@view
@external
def stored_rates() -> DynArray[uint256, MAX_COINS]:
    return self._stored_rates()


@view
@external
def dynamic_fee(i: int128, j: int128) -> uint256:
    """
    @notice Return the fee for swapping between `i` and `j`
    @param i Index value for the coin to send
    @param j Index value of the coin to recieve
    @return Swap fee expressed as an integer with 1e10 precision
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).dynamic_fee(i, j, self)


# --------------------------- AMM Admin Functions ----------------------------


@external
def ramp_A(_future_A: uint256, _future_time: uint256):
    assert msg.sender == staticcall factory.admin()  # dev: only owner
    assert block.timestamp >= self.initial_A_time + MIN_RAMP_TIME
    assert _future_time >= block.timestamp + MIN_RAMP_TIME  # dev: insufficient time

    _initial_A: uint256 = self._A()
    _future_A_p: uint256 = _future_A * A_PRECISION

    assert _future_A > 0 and _future_A < MAX_A
    if _future_A_p < _initial_A:
        assert _future_A_p * MAX_A_CHANGE >= _initial_A
    else:
        assert _future_A_p <= _initial_A * MAX_A_CHANGE

    self.initial_A = _initial_A
    self.future_A = _future_A_p
    self.initial_A_time = block.timestamp
    self.future_A_time = _future_time

    log RampA(old_A=_initial_A, new_A=_future_A_p, initial_time=block.timestamp, future_time=_future_time)


@external
def stop_ramp_A():
    assert msg.sender == staticcall factory.admin()  # dev: only owner

    current_A: uint256 = self._A()
    self.initial_A = current_A
    self.future_A = current_A
    self.initial_A_time = block.timestamp
    self.future_A_time = block.timestamp
    # now (block.timestamp < t1) is always False, so we return saved A

    log StopRampA(A=current_A, t=block.timestamp)


@external
def set_new_fee(_new_fee: uint256, _new_offpeg_fee_multiplier: uint256):

    assert msg.sender == staticcall factory.admin()

    # set new fee:
    assert _new_fee <= MAX_FEE
    self.fee = _new_fee

    # set new offpeg_fee_multiplier:
    assert _new_offpeg_fee_multiplier * _new_fee <= MAX_FEE * FEE_DENOMINATOR  # dev: offpeg multiplier exceeds maximum
    self.offpeg_fee_multiplier = _new_offpeg_fee_multiplier

    log ApplyNewFee(fee=_new_fee, offpeg_fee_multiplier=_new_offpeg_fee_multiplier)


@external
def set_ma_exp_time(_ma_exp_time: uint256, _D_ma_time: uint256):
    """
    @notice Set the moving average window of the price oracles.
    @param _ma_exp_time Moving average window. It is time_in_seconds // ln(2)
    """
    assert msg.sender == staticcall factory.admin()  # dev: only owner
    assert 0 not in [_ma_exp_time, _D_ma_time]

    self.ma_exp_time = _ma_exp_time
    self.D_ma_time = _D_ma_time
