# pragma version >=0.4.2

"""
@title CurveStableSwapMeta
@custom:version 7.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Stableswap Metapool implementation for 2 coins. Supports pegged assets.
@dev Metapools are pools where the coin on index 1 is a liquidity pool token
     of another pool. This exposes methods such as exchange_underlying, which
     exchanges token 0 <> token b1, b2, .. bn, where b is base pool and bn is the
     nth coin index of the base pool.
     CAUTION: Does not work if base pool is an NG pool. Use a different metapool
              implementation index in the staticcall factory.
     Asset Types:
        0. Standard IERC20 token with no additional features.
                          Note: Users are advised to do careful due-diligence on
                                IERC20 tokens that they interact with, as this
                                contract cannot differentiate between harmless and
                                malicious IERC20 tokens.
        1. Oracle - token with rate oracle (e.g. wstETH)
                    Note: Oracles may be controlled externally by an EOA. Users
                          are advised to proceed with caution.
        2. Rebasing - token with rebase (e.g. stETH).
                      Note: Users and Integrators are advised to understand how
                            the AMM contract works with rebasing balances.
        3. IERC4626 - token with convertToAssets method (e.g. sDAI).
                     Note: Some IERC4626 implementations may be susceptible to
                           Donation//Inflation attacks. Users are advised to
                           proceed with caution.
        NOTE: Pool Cannot support tokens with multiple asset types: e.g. IERC4626
              with fees are not supported.
     Supports:
        1. IERC20 support for return True//revert, return True//False, return None
        2. IERC20 tokens can have arbitrary decimals (<=18).
        3. IERC20 tokens that rebase (either positive or fee on transfer)
        4. IERC20 tokens that have a rate oracle (e.g. wstETH, cbETH, sDAI, etc.)
           Note: Oracle precision _must_ be 10**18.
        5. IERC4626 tokens with arbitrary precision (<=18) of Vault token and underlying
           asset.
     Additional features include:
        1. Adds oracles based on AMM State Price (and _not_ last traded price).
           State prices are calculated _after_ liquidity operations, using bonding
           curve staticcall math.
        2. Adds an exponential moving average oracle for D.
        3. `exchange_received`: swaps that expect an IERC20 transfer to have occurred
           prior to executing the swap.
           Note: a. If pool contains rebasing tokens and one of the `asset_types` is 2 (Rebasing)
                    then calling `exchange_received` will REVERT.
                 b. If pool contains rebasing token and `asset_types` does not contain 2 (Rebasing)
                    then this is an incorrect implementation and rebases can be
                    stolen.
        4. Adds `get_dx`, `get_dx_underlying`: Similar to `get_dy` which returns an expected output
           of coin[j] for given `dx` amount of coin[i], `get_dx` returns expected
           input of coin[i] for an output amount of coin[j].
        5. Fees are dynamic: AMM will charge a higher fee if pool depegs. This can cause very
                             slight discrepancies between calculated fees and realised fees.
"""

from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed
from ethereum.ercs import IERC4626

implements: IERC20

# ------------------------------- Version ------------------------------------

version: public(constant(String[8])) = "7.0.0"

# ------------------------------- Interfaces ---------------------------------

interface Factory:
    def fee_receiver() -> address: view
    def admin() -> address: view
    def views_implementation() -> address: view

interface ERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes32: view

interface StableSwapViews:
    def get_dx(i: int128, j: int128, dy: uint256, pool: address) -> uint256: view
    def get_dy(i: int128, j: int128, dx: uint256, pool: address) -> uint256: view
    def get_dx_underlying(i: int128, j: int128, dy: uint256, pool: address) -> uint256: view
    def get_dy_underlying(i: int128, j: int128, dx: uint256, pool: address) -> uint256: view
    def dynamic_fee(i: int128, j: int128, pool: address) -> uint256: view
    def calc_token_amount(
        _amounts: DynArray[uint256, MAX_COINS],
        _is_deposit: bool,
        _pool: address
    ) -> uint256: view

interface StableSwap2:
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256): nonpayable

interface StableSwap3:
    def add_liquidity(amounts: uint256[3], min_mint_amount: uint256): nonpayable

interface StableSwapNG:
    def add_liquidity(
        amounts: DynArray[uint256, MAX_COINS],
        min_mint_amount: uint256
    ) -> uint256: nonpayable

interface StableSwap:
    def remove_liquidity_one_coin(_token_amount: uint256, i: int128, min_amount: uint256): nonpayable
    def exchange(i: int128, j: int128, dx: uint256, min_dy: uint256): nonpayable
    def get_virtual_price() -> uint256: view

interface Math:
    def get_y(
        i: int128,
        j: int128,
        x: uint256,
        xp: DynArray[uint256, MAX_COINS],
        _amp: uint256,
        _D: uint256,
        _n_coins: uint256
    ) -> uint256: view
    def get_y_D(
        A: uint256,
        i: int128,
        xp: DynArray[uint256, MAX_COINS],
        D: uint256,
        _n_coins: uint256
    ) -> uint256: view
    def get_D(
        _xp: DynArray[uint256, MAX_COINS],
        _amp: uint256,
        _n_coins: uint256
    ) -> uint256: view
    def exp(x: int256) -> uint256: view

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
    sold_id: int128
    tokens_sold: uint256
    bought_id: int128
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
    token_id: int128
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

event SetNewMATime:
    ma_exp_time: uint256
    D_ma_time: uint256


MAX_COINS: constant(uint256) = 8  # max coins is 8 in the factory
MAX_COINS_128: constant(int128) = 8
MAX_METAPOOL_COIN_INDEX: constant(int128) = 1

# ---------------------------- Pool Variables --------------------------------

N_COINS: public(constant(uint256)) = 2
N_COINS_128: constant(uint256) = 2
PRECISION: constant(uint256) = 10 ** 18

BASE_POOL: public(immutable(address))
BASE_POOL_IS_NG: immutable(bool)
BASE_N_COINS: public(immutable(uint256))
BASE_COINS: public(immutable(DynArray[address, MAX_COINS]))

math: immutable(Math)
factory: immutable(Factory)
coins: public(immutable(DynArray[address, MAX_COINS]))
asset_type: immutable(uint8)
pool_contains_rebasing_tokens: immutable(bool)
stored_balances: uint256[N_COINS]

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

rate_multiplier: immutable(uint256)
# [bytes4 method_id][bytes8 <empty>][bytes20 oracle]
rate_oracle: immutable(uint256)  # this is the rate oracle for the token at 0th index

# For IERC4626 tokens, we need:
call_amount: immutable(uint256)
scale_factor: immutable(uint256)

last_prices_packed: uint256                       #  packing: last_price, ma_price
last_D_packed: uint256                            #  packing: last_D, ma_D
ma_exp_time: public(uint256)
D_ma_time: public(uint256)
ma_last_time: public(uint256)                     # packing: ma_last_time_p, ma_last_time_D

# shift(2**32 - 1, 224)
ORACLE_BIT_MASK: constant(uint256) = (2**32 - 1) * 256**28

# --------------------------- IERC20 Specific Vars ----------------------------

name: public(immutable(String[64]))
symbol: public(immutable(String[32]))
decimals: public(constant(uint8)) = 18

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


@deploy
def __init__(
    _name: String[32],
    _symbol: String[10],
    _A: uint256,
    _fee: uint256,
    _offpeg_fee_multiplier: uint256,
    _ma_exp_time: uint256,
    _math_implementation: address,
    _base_pool: address,
    _coins: DynArray[address, MAX_COINS],
    _base_coins: DynArray[address, MAX_COINS],
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
                                  Fees by when assets in the AMM depeg. Example: 20000000000
    @param _ma_exp_time Averaging window of oracle. Set as time_in_seconds // ln(2)
                        Example: for 10 minute EMA, _ma_exp_time is 600 // ln(2) ~= 866
    @param _math_implementation Contract containing Math methods
    @param _base_pool The underlying AMM of the LP token _coins[0] is paired against
    @param _coins List of addresses of the coins being used in the pool. For metapool this is
                  the coin (say LUSD) vs (say) 3crv as: [LUSD, 3CRV]. Length is always 2.
    @param _base_coins coins in the underlying base pool.
    @param _rate_multipliers Rate multipliers of the individual coins. For Metapools it is:
                              [10 ** (36 - _coins[0].decimals()), 10 ** 18].
    @param _asset_types Array of uint8 representing tokens in pool
    @param _method_ids Array of first four bytes of the Keccak-256 hash of the function signatures
                       of the oracle addresses that gives rate oracles.
                       Calculated as: keccak(text=event_signature.replace(" ", ""))[:4]
    @param _oracles Array of rate oracle addresses.
    """
    # The following reverts if BASE_POOL is an NG implementaion.
    BASE_POOL_IS_NG = raw_call(_base_pool, method_id("D_ma_time()"), revert_on_failure=False)

    if not BASE_POOL_IS_NG:
        assert len(_base_coins) <= 3  # dev: implementation does not support old gen base pool with more than 3 coins

    math = Math(_math_implementation)
    BASE_POOL = _base_pool
    BASE_COINS = _base_coins
    BASE_N_COINS = len(_base_coins)
    coins = _coins  # <---------------- coins[1] is always base pool LP token.

    asset_type = _asset_types[0]
    pool_contains_rebasing_tokens = asset_type == 2
    rate_multiplier = _rate_multipliers[0]

    for i: uint256 in range(MAX_COINS):
        if i < BASE_N_COINS:
            # Approval needed for add_liquidity operation on base pool in
            # _exchange_underlying:
            assert extcall IERC20(_base_coins[i]).approve(
                BASE_POOL,
                max_value(uint256),
                default_return_value = True
            )

    # For IERC4626 tokens:
    if asset_type == 3:
        # In Vyper 0.3.10, if immutables are not set, because of an if-statement,
        # it is by default set to 0; this is fine in the case of these two
        # immutables, since they are only used if asset_types[0] == 3.
        call_amount = 10**convert(staticcall IERC20Detailed(_coins[0]).decimals(), uint256)
        scale_factor = 10**(18 - convert(staticcall IERC20Detailed(staticcall IERC4626(_coins[0]).asset()).decimals(), uint256))

    # ----------------- Parameters independent of pool type ------------------

    factory = Factory(msg.sender)

    A: uint256 = unsafe_mul(_A, A_PRECISION)
    self.initial_A = A
    self.future_A = A
    self.fee = _fee
    self.offpeg_fee_multiplier = _offpeg_fee_multiplier

    assert _ma_exp_time != 0
    self.ma_exp_time = _ma_exp_time
    self.D_ma_time = 62324  # <--------- 12 hours default on contract start.
    self.ma_last_time = self.pack_2(block.timestamp, block.timestamp)

    self.last_prices_packed = self.pack_2(10**18, 10**18)
    self.admin_balances = [0, 0]
    self.stored_balances = [0, 0]

    rate_oracle = convert(_method_ids[0], uint256) * 2**224 | convert(_oracles[0], uint256)

    # --------------------------- IERC20 stuff ----------------------------

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
    coin_metapool_idx: uint256,
    coin_basepool_idx: int128,
    dx: uint256,
    sender: address,
    expect_optimistic_transfer: bool,
    is_base_pool_swap: bool = False,
) -> uint256:
    """
    @notice Contains all logic to handle IERC20 token transfers.
    @param coin_metapool_idx metapool index of input coin
    @param coin_basepool_idx basepool index of input coin
    @param dx amount of `_coin` to transfer into the pool.
    @param sender address to transfer `_coin` from.
    @param expect_optimistic_transfer True if contract expects an optimistic coin transfer
    @param is_base_pool_swap Default is set to False.
    @return amount of coins received
    """
    _input_coin: IERC20 = IERC20(coins[coin_metapool_idx])
    _input_coin_is_in_base_pool: bool = False

    # Check if _transfer_in is being called by _exchange_underlying:
    if coin_basepool_idx >= 0 and coin_metapool_idx == 1:

        _input_coin = IERC20(BASE_COINS[coin_basepool_idx])
        _input_coin_is_in_base_pool = True

    _dx: uint256 = staticcall _input_coin.balanceOf(self)

    # ------------------------- Handle Transfers -----------------------------

    if expect_optimistic_transfer:

        if not _input_coin_is_in_base_pool:
            _dx = _dx - self.stored_balances[coin_metapool_idx]
            assert _dx >= dx  # dev: pool did not receive tokens for swap

    else:

        assert dx > 0  # dev : do not transferFrom 0 tokens into the pool
        assert extcall _input_coin.transferFrom(
            sender,
            self,
            dx,
            default_return_value=True
        )
        _dx = staticcall _input_coin.balanceOf(self) - _dx

    # ------------ Check if liquidity needs to be added somewhere ------------

    if _input_coin_is_in_base_pool:
        if is_base_pool_swap:
            return _dx  # <----- _exchange_underlying: all input goes to swap.
            # So, we will not increment self.stored_balances for metapool_idx.

        # Swap involves base <> meta pool interaction. Add incoming base pool
        # token to the base pool, mint _dx base pool LP token (idx 1) and add
        # that to self.stored_balances and return that instead.
        _dx = self._meta_add_liquidity(_dx, coin_basepool_idx)

    # ----------------------- Update Stored Balances -------------------------

    self.stored_balances[coin_metapool_idx] += _dx

    return _dx


@internal
def _transfer_out(
    _coin_idx: uint256, _amount: uint256, receiver: address
):
    """
    @notice Transfer a single token from the pool to receiver.
    @dev This function is called by `remove_liquidity` and
         `remove_liquidity_one_coin`, `_exchange`, `_withdraw_admin_fees` and
         `remove_liquidity_imbalance` methods.
    @param _coin_idx Index of the token to transfer out
    @param _amount Amount of token to transfer out
    @param receiver Address to send the tokens to
    """
    assert receiver != empty(address)  # dev: do not send tokens to zero_address

    if not pool_contains_rebasing_tokens:

        # we need not cache balanceOf pool before swap out
        self.stored_balances[_coin_idx] -= _amount
        assert extcall IERC20(coins[_coin_idx]).transfer(
            receiver, _amount, default_return_value=True
        )

    else:

        # cache balances pre and post to account for fee on transfers etc.
        coin_balance: uint256 = staticcall IERC20(coins[_coin_idx]).balanceOf(self)
        assert extcall IERC20(coins[_coin_idx]).transfer(
            receiver, _amount, default_return_value=True
        )
        self.stored_balances[_coin_idx] = coin_balance - _amount


# -------------------------- AMM Special Methods -----------------------------


@view
@internal
def _stored_rates() -> uint256[N_COINS]:
    """
    @notice Gets rate multipliers for each coin.
    @dev If the coin has a rate oracle that has been properly initialised,
         this method queries that rate by static-calling an external
         contract.
    """
    rates: uint256[N_COINS] = [rate_multiplier, staticcall StableSwap(BASE_POOL).get_virtual_price()]

    if asset_type == 1 and not rate_oracle == 0:

        # NOTE: fetched_rate is assumed to be 10**18 precision
        oracle_response: Bytes[32] = raw_call(
            convert(rate_oracle % 2**160, address),
            abi_encode(rate_oracle & ORACLE_BIT_MASK),
            max_outsize=32,
            is_static_call=True,
        )
        assert len(oracle_response) == 32
        fetched_rate: uint256 = convert(oracle_response, uint256)

        # rates[0] * fetched_rate // PRECISION
        rates[0] = unsafe_div(rates[0] * fetched_rate, PRECISION)

    elif asset_type == 3:  # IERC4626

        # rates[0] * fetched_rate // PRECISION
        rates[0] = unsafe_div(
            rates[0] * staticcall IERC4626(coins[0]).convertToAssets(call_amount) * scale_factor,
            PRECISION
        )  # 1e18 precision

    return rates


@view
@internal
def _balances() -> uint256[N_COINS]:
    """
    @notice Calculates the pool's balances _excluding_ the admin's balances.
    @dev If the pool contains rebasing tokens, this method ensures LPs keep all
         rebases and admin only claims swap fees. This also means that, since
         admin's balances are stored in an array and not inferred from read balances,
         the fees in the rebasing token that the admin collects is immune to
         slashing events.
    """
    result: uint256[N_COINS] = empty(uint256[N_COINS])
    admin_balances: DynArray[uint256, MAX_COINS] = self.admin_balances
    for i: uint256 in range(N_COINS_128):

        if pool_contains_rebasing_tokens:
            # Read balances by gulping to account for rebases
            result[i] = staticcall IERC20(coins[i]).balanceOf(self) - admin_balances[i]
        else:
            # Use cached balances
            result[i] = self.stored_balances[i] - admin_balances[i]

    return result


# -------------------------- AMM Main Functions ------------------------------


@external
@nonreentrant
def exchange(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
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
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins without transferring token in
    @dev The contract swaps tokens based on a change in balance of coin[i]. The
         dx = staticcall IERC20(coin[i]).balanceOf(self) - self.stored_balances[i]. Users of
         this method are dex aggregators, arbitrageurs, or other users who do not
         wish to grant approvals to the contract: they would instead send tokens
         directly to the contract and call `exchange_received`.
         Note: This is disabled if pool contains rebasing tokens.
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
    @return Actual amount of `j` received
    """
    assert not pool_contains_rebasing_tokens  # dev: exchange_received not supported if pool contains rebasing tokens
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
def exchange_underlying(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two underlying coins
    @param i Index value for the underlying coin to send
    @param j Index value of the underlying coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
    @return Actual amount of `j` received
    """
    assert _receiver != empty(address)  # dev: do not send tokens to zero_address

    rates: uint256[N_COINS] = self._stored_rates()
    old_balances: uint256[N_COINS] = self._balances()
    xp: uint256[N_COINS]  = self._xp_mem(rates, old_balances)

    dy: uint256 = 0
    base_i: int128 = 0
    base_j: int128 = 0
    meta_i: int128 = 0
    meta_j: int128 = 0
    x: uint256 = 0
    output_coin: address = empty(address)

    # ------------------------ Determine coin indices ------------------------

    # Get input coin indices:
    if i > 0:
        base_i = i - MAX_METAPOOL_COIN_INDEX
        meta_i = 1

    # Get output coin and indices:
    if j == 0:
        output_coin = coins[0]
    else:
        base_j = j - MAX_METAPOOL_COIN_INDEX
        meta_j = 1
        output_coin = BASE_COINS[base_j]

    # --------------------------- Do Transfer in -----------------------------

    # If incoming coin is supposed to go to the base pool, the _transfer_in
    # method will add_liquidity in the base pool and return dx_w_fee LP tokens
    dx_w_fee: uint256 =  self._transfer_in(
        convert(meta_i, uint256),
        base_i,
        _dx,
        msg.sender,
        False,
        (i > 0 and j > 0),  # <--- if True: do not add liquidity to base pool.
    )

    # ------------------------------- Exchange -------------------------------

    if i == 0 or j == 0:  # meta swap

        x = xp[meta_i] + unsafe_div(dx_w_fee * rates[meta_i], PRECISION)
        dy = self.__exchange(x, xp, rates, meta_i, meta_j)

        # Adjust stored balances of meta-level tokens:
        self.stored_balances[meta_j] -= dy

        # Withdraw from the base pool if needed
        if j > 0:
            out_amount: uint256 = staticcall IERC20(output_coin).balanceOf(self)
            extcall StableSwap(BASE_POOL).remove_liquidity_one_coin(dy, base_j, 0)
            dy = staticcall IERC20(output_coin).balanceOf(self) - out_amount

        assert dy >= _min_dy

    else:  # base pool swap (user should swap at base pool for better gas)

        dy = staticcall IERC20(output_coin).balanceOf(self)
        extcall StableSwap(BASE_POOL).exchange(base_i, base_j, dx_w_fee, _min_dy)
        dy = staticcall IERC20(output_coin).balanceOf(self) - dy

    # --------------------------- Do Transfer out ----------------------------

    assert extcall IERC20(output_coin).transfer(_receiver, dy, default_return_value=True)

    # ------------------------------------------------------------------------

    log TokenExchangeUnderlying(buyer=msg.sender, sold_id=i, tokens_sold=_dx, bought_id=j, tokens_bought=dy)

    return dy


@external
@nonreentrant
def add_liquidity(
    _amounts: uint256[N_COINS],
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
    assert _receiver != empty(address)  # dev: do not send LP tokens to zero_address

    amp: uint256 = self._A()
    old_balances: uint256[N_COINS] = self._balances()
    rates: uint256[N_COINS] = self._stored_rates()

    # Initial invariant
    D0: uint256 = self.get_D_mem(rates, old_balances, amp)

    total_supply: uint256 = self.total_supply
    new_balances: uint256[N_COINS] = old_balances

    # -------------------------- Do Transfers In -----------------------------

    for i: uint256 in range(N_COINS_128):

        if _amounts[i] > 0:

            new_balances[i] += self._transfer_in(
                i,
                -1,  # <--- we're not handling underlying coins here
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
    fees: uint256[N_COINS] = empty(uint256[N_COINS])
    mint_amount: uint256 = 0

    if total_supply > 0:

        ideal_balance: uint256 = 0
        difference: uint256 = 0
        new_balance: uint256 = 0

        ys: uint256 = unsafe_div(D0 + D1, N_COINS)
        xs: uint256 = 0
        _dynamic_fee_i: uint256 = 0

        # Only account for fees if we are not the first to deposit
        # base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
        # unsafe math is safu here:
        base_fee: uint256 = unsafe_div(unsafe_mul(self.fee, N_COINS), 4)

        for i: uint256 in range(N_COINS_128):

            ideal_balance = D1 * old_balances[i] // D0
            new_balance = new_balances[i]

            # unsafe math is safu here:
            if ideal_balance > new_balance:
                difference = unsafe_sub(ideal_balance, new_balance)
            else:
                difference = unsafe_sub(new_balance, ideal_balance)

            # fee[i] = _dynamic_fee(i, j) * difference // FEE_DENOMINATOR
            xs = unsafe_div(rates[i] * (old_balances[i] + new_balance), PRECISION)
            _dynamic_fee_i = self._dynamic_fee(xs, ys, base_fee)
            fees[i] = unsafe_div(_dynamic_fee_i * difference, FEE_DENOMINATOR)

            # fees[i] * admin_fee // FEE_DENOMINATOR
            self.admin_balances[i] += unsafe_div(fees[i] * admin_fee, FEE_DENOMINATOR)
            new_balances[i] -= fees[i]

        xp: uint256[N_COINS] = self._xp_mem(rates, new_balances)
        D1 = staticcall math.get_D([xp[0], xp[1]], amp, N_COINS)  # <------ Reuse D1 for new D value.
        # we do unsafe div here because we already did several safedivs with D0
        mint_amount = unsafe_div(total_supply * (D1 - D0), D0)
        self.upkeep_oracles(xp, amp, D1)

    else:

        mint_amount = D1  # Take the dust if there was any

        # (re)instantiate D oracle if totalSupply is zero.
        self.last_D_packed = self.pack_2(D1, D1)

        # Update D ma time:
        ma_last_time_unpacked: uint256[2] = self.unpack_2(self.ma_last_time)
        if ma_last_time_unpacked[1] < block.timestamp:
            ma_last_time_unpacked[1] = block.timestamp
            self.ma_last_time = self.pack_2(ma_last_time_unpacked[0], ma_last_time_unpacked[1])

    assert mint_amount >= _min_mint_amount, "Slippage screwed you"

    # Mint pool tokens
    total_supply += mint_amount
    user_lp_token_bal: uint256 = self.balanceOf[_receiver]

    # here we can increase balance using unsafe add because
    # user balance will always be <= total_supply. so if total_supply
    # safeadd works, this can be safely unsafe:
    self.balanceOf[_receiver] = unsafe_add(user_lp_token_bal, mint_amount)
    self.total_supply = total_supply
    log Transfer(sender=empty(address), receiver=_receiver, value=mint_amount)

    log AddLiquidity(
        provider=msg.sender,
        token_amounts=[_amounts[0], _amounts[1]],
        fees=[fees[0], fees[1]],
        invariant=D1,
        token_supply=total_supply
    )

    return mint_amount


@external
@nonreentrant
def remove_liquidity_one_coin(
    _burn_amount: uint256,
    i: int128,
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
    xp: uint256[N_COINS] = empty(uint256[N_COINS])
    amp: uint256 = empty(uint256)
    D: uint256 = empty(uint256)

    dy, fee, xp, amp, D = self._calc_withdraw_one_coin(_burn_amount, i)
    assert dy >= _min_received, "Not enough coins removed"

    # fee * admin_fee // FEE_DENOMINATOR
    self.admin_balances[i] += unsafe_div(fee * admin_fee, FEE_DENOMINATOR)

    self._burnFrom(msg.sender, _burn_amount)

    self._transfer_out(convert(i, uint256), dy, _receiver)

    log RemoveLiquidityOne(provider=msg.sender, token_id=i, token_amount=_burn_amount, coin_amount=dy, token_supply=self.total_supply)

    self.upkeep_oracles(xp, amp, D)

    return dy


@external
@nonreentrant
def remove_liquidity_imbalance(
    _amounts: uint256[N_COINS],
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
    rates: uint256[N_COINS] = self._stored_rates()
    old_balances: uint256[N_COINS] = self._balances()
    D0: uint256 = self.get_D_mem(rates, old_balances, amp)
    new_balances: uint256[N_COINS] = old_balances

    for i: uint256 in range(N_COINS_128):

        if _amounts[i] != 0:
            new_balances[i] -= _amounts[i]
            self._transfer_out(i, _amounts[i], _receiver)

    D1: uint256 = self.get_D_mem(rates, new_balances, amp)
    # base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
    base_fee: uint256 = unsafe_div(unsafe_mul(self.fee, N_COINS), 4)
    # ys: uint256 = (D0 + D1) // N_COINS
    ys: uint256 = unsafe_div(D0 + D1, N_COINS)

    fees: uint256[N_COINS] = empty(uint256[N_COINS])
    dynamic_fee: uint256 = 0
    xs: uint256 = 0
    ideal_balance: uint256 = 0
    difference: uint256 = 0
    new_balance: uint256 = 0

    for i: uint256 in range(N_COINS_128):

        ideal_balance = D1 * old_balances[i] // D0
        new_balance = new_balances[i]

        if ideal_balance > new_balance:
            difference = unsafe_sub(ideal_balance, new_balance)
        else:
            difference = unsafe_sub(new_balance, ideal_balance)

        # base_fee * difference // FEE_DENOMINATOR
        xs = unsafe_div(rates[i] * (old_balances[i] + new_balance), PRECISION)
        dynamic_fee = self._dynamic_fee(xs, ys, base_fee)
        fees[i] = unsafe_div(dynamic_fee * difference, FEE_DENOMINATOR)

        # fees[i] * admin_fee // FEE_DENOMINATOR
        self.admin_balances[i] += unsafe_div(fees[i] * admin_fee, FEE_DENOMINATOR)

        new_balances[i] -= fees[i]

    D1 = self.get_D_mem(rates, new_balances, amp)  # dev: reuse D1 for new D.
    self.upkeep_oracles(self._xp_mem(rates, new_balances), amp, D1)

    total_supply: uint256 = self.total_supply
    # here we can do unsafe div by D0 because we did several safedivs:
    # burn_amount: uint256 = ((D0 - D1) * total_supply // D0) + 1
    burn_amount: uint256 = unsafe_div((D0 - D1) * total_supply, D0) + 1
    assert burn_amount > 1  # dev: zero tokens burned
    assert burn_amount <= _max_burn_amount, "Slippage screwed you"

    self._burnFrom(msg.sender, burn_amount)

    log RemoveLiquidityImbalance(
        provider=msg.sender,
        token_amounts=[_amounts[0], _amounts[1]],
        fees=[fees[0], fees[1]],
        invariant=D1,
        token_supply=total_supply - burn_amount
    )

    return burn_amount


@external
@nonreentrant
def remove_liquidity(
    _burn_amount: uint256,
    _min_amounts: uint256[N_COINS],
    _receiver: address = msg.sender,
    _claim_admin_fees: bool = True,
) -> uint256[N_COINS]:
    """
    @notice Withdraw coins from the pool
    @dev Withdrawal amounts are based on current deposit ratios
    @param _burn_amount Quantity of LP tokens to burn in the withdrawal
    @param _min_amounts Minimum amounts of underlying coins to receive
    @param _receiver Address that receives the withdrawn coins
    @return List of amounts of coins that were withdrawn
    """
    total_supply: uint256 = self.total_supply
    assert _burn_amount > 0  # dev: invalid _burn_amount
    amounts: uint256[N_COINS] = empty(uint256[N_COINS])
    balances: uint256[N_COINS] = self._balances()

    value: uint256 = 0

    for i: uint256 in range(N_COINS_128):

        value = unsafe_div(balances[i] * _burn_amount, total_supply)
        assert value >= _min_amounts[i], "Withdrawal resulted in fewer coins than expected"
        amounts[i] = value
        self._transfer_out(i, value, _receiver)

    self._burnFrom(msg.sender, _burn_amount)  # dev: insufficient funds

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
        token_amounts=[amounts[0], amounts[1]],
        fees=empty(DynArray[uint256, MAX_COINS]),
        token_supply=unsafe_sub(total_supply, _burn_amount)
    )

    # ------- Withdraw admin fees if _claim_admin_fees is set to True --------

    if _claim_admin_fees:
        self._withdraw_admin_fees()

    return [amounts[0], amounts[1]]


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

    # to remove dynamic fee: just set _offpeg_fee_multiplier less than FEE_DENOMINATOR
    if _offpeg_fee_multiplier <= FEE_DENOMINATOR:
        return _fee

    xps2: uint256 = (xpi + xpj) ** 2
    return unsafe_div(
        unsafe_mul(_offpeg_fee_multiplier, _fee),
        unsafe_add(
            unsafe_sub(_offpeg_fee_multiplier, FEE_DENOMINATOR) * 4 * xpi * xpj // xps2,
            FEE_DENOMINATOR
        )
    )


@internal
def __exchange(
    x: uint256,
    _xp: uint256[N_COINS],
    rates: uint256[N_COINS],
    i: int128,
    j: int128,
) -> uint256:

    amp: uint256 = self._A()
    D: uint256 = staticcall math.get_D([_xp[0], _xp[1]], amp, N_COINS)
    y: uint256 = staticcall math.get_y(i, j, x, [_xp[0], _xp[1]], amp, D, N_COINS)

    dy: uint256 = _xp[j] - y - 1  # -1 just in case there were some rounding errors
    dy_fee: uint256 = unsafe_div(
        dy * self._dynamic_fee(
            unsafe_div(_xp[i] + x, 2), unsafe_div(_xp[j] + y, 2), self.fee
        ),
        FEE_DENOMINATOR
    )

    # Convert all to real units
    dy = (dy - dy_fee) * PRECISION // rates[j]

    # admin_fee = dy_fee * admin_fee // FEE_DENOMINATOR
    self.admin_balances[j] += unsafe_div(
        unsafe_div(dy_fee * admin_fee, FEE_DENOMINATOR) * PRECISION,
        rates[j]  # we can do unsafediv here because we did safediv before
    )

    # Calculate and store state prices:
    xp: uint256[N_COINS] = _xp
    xp[i] = x
    xp[j] = y
    # D is not changed because we did not apply a fee
    self.upkeep_oracles(xp, amp, D)

    return dy


@internal
def _exchange(
    sender: address,
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    receiver: address,
    expect_optimistic_transfer: bool
) -> uint256:

    assert i != j  # dev: coin index out of range
    assert _dx > 0  # dev: do not exchange 0 coins

    rates: uint256[N_COINS] = self._stored_rates()
    old_balances: uint256[N_COINS] = self._balances()
    xp: uint256[N_COINS] = self._xp_mem(rates, old_balances)

    # --------------------------- Do Transfer in -----------------------------

    # `dx` is whatever the pool received after IERC20 transfer:
    dx: uint256 = self._transfer_in(
        convert(i, uint256),
        -1,
        _dx,
        sender,
        expect_optimistic_transfer
    )

    # ------------------------------- Exchange -------------------------------

    # xp[i] + dx * rates[i] // PRECISION
    x: uint256 = xp[i] + unsafe_div(dx * rates[i], PRECISION)
    dy: uint256 = self.__exchange(x, xp, rates, i, j)
    assert dy >= _min_dy, "Exchange resulted in fewer coins than expected"

    # --------------------------- Do Transfer out ----------------------------

    self._transfer_out(convert(j, uint256), dy, receiver)

    # ------------------------------------------------------------------------

    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=dx, bought_id=j, tokens_bought=dy)

    return dy


@internal
def _meta_add_liquidity(dx: uint256, base_i: int128) -> uint256:

    if BASE_POOL_IS_NG:

        base_inputs: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
        for i: uint256 in range(BASE_N_COINS, bound=MAX_COINS):
            if i == convert(base_i, uint256):
                base_inputs.append(dx)
            else:
                base_inputs.append(0)
        return extcall StableSwapNG(BASE_POOL).add_liquidity(base_inputs, 0)

    coin_i: address = coins[MAX_METAPOOL_COIN_INDEX]
    x: uint256 = staticcall IERC20(coin_i).balanceOf(self)

    if BASE_N_COINS == 2:

        base_inputs: uint256[2] = empty(uint256[2])
        base_inputs[base_i] = dx
        extcall StableSwap2(BASE_POOL).add_liquidity(base_inputs, 0)

    if BASE_N_COINS == 3:

        base_inputs: uint256[3] = empty(uint256[3])
        base_inputs[base_i] = dx
        extcall StableSwap3(BASE_POOL).add_liquidity(base_inputs, 0)

    return staticcall IERC20(coin_i).balanceOf(self) - x


@internal
def _withdraw_admin_fees():

    fee_receiver: address = staticcall factory.fee_receiver()
    if fee_receiver == empty(address):
        return  # Do nothing.

    admin_balances: DynArray[uint256, MAX_COINS] = self.admin_balances
    for i: uint256 in range(N_COINS_128):

        if admin_balances[i] > 0:
            self._transfer_out(i, admin_balances[i], fee_receiver)

    self.admin_balances = [0, 0]


# --------------------------- AMM Math Functions -----------------------------


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
            return A0 + unsafe_sub(A1, A0) * (block.timestamp - t0) // (t1 - t0)
        else:
            return A0 - unsafe_sub(A0, A1) * (block.timestamp - t0) // (t1 - t0)

    else:  # when t1 == 0 or block.timestamp >= t1
        return A1


@pure
@internal
def _xp_mem(_rates: uint256[N_COINS], _balances: uint256[N_COINS]) -> uint256[N_COINS]:

    result: uint256[N_COINS] = empty(uint256[N_COINS])
    for i: uint256 in range(N_COINS_128):
        # _rates[i] * _balances[i] // PRECISION
        result[i] = unsafe_div(_rates[i] * _balances[i], PRECISION)

    return result


@view
@internal
def get_D_mem(
    _rates: uint256[N_COINS],
    _balances: uint256[N_COINS],
    _amp: uint256
) -> uint256:
    xp: uint256[N_COINS] = self._xp_mem(_rates, _balances)
    return staticcall math.get_D([xp[0], xp[1]], _amp, N_COINS)


@view
@internal
def _calc_withdraw_one_coin(
    _burn_amount: uint256,
    i: int128
) -> (
    uint256,
    uint256,
    uint256[N_COINS],
    uint256,
    uint256
):

    # First, need to:
    # * Get current D
    # * Solve Eqn against y_i for D - _token_amount

    # get pool state
    amp: uint256 = self._A()
    rates: uint256[N_COINS] = self._stored_rates()
    xp: uint256[N_COINS] = self._xp_mem(rates, self._balances())
    D0: uint256 = staticcall math.get_D([xp[0], xp[1]], amp, N_COINS)

    total_supply: uint256 = self.total_supply
    D1: uint256 = D0 - _burn_amount * D0 // total_supply
    new_y: uint256 = staticcall math.get_y_D(amp, i, [xp[0], xp[1]], D1, N_COINS)

    base_fee: uint256 = unsafe_div(unsafe_mul(self.fee, N_COINS), 4)
    xp_reduced: uint256[N_COINS] = xp
    # ys: uint256 = (D0 + D1) // (2 * N_COINS)
    ys: uint256 = unsafe_div((D0 + D1), 4)
    # base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))

    dx_expected: uint256 = 0
    xp_j: uint256 = 0
    xavg: uint256 = 0
    dynamic_fee: uint256 = 0

    for j: uint256 in range(N_COINS_128):

        dx_expected = 0
        xp_j = xp[j]
        if j == convert(i, uint256):
            dx_expected = xp_j * D1 // D0 - new_y
            xavg = unsafe_div(xp_j + new_y, 2)
        else:
            dx_expected = xp_j - xp_j * D1 // D0
            xavg = xp_j

        # xp_j - dynamic_fee * dx_expected // FEE_DENOMINATOR
        dynamic_fee = self._dynamic_fee(xavg, ys, base_fee)
        xp_reduced[j] = xp_j - unsafe_div(dynamic_fee * dx_expected, FEE_DENOMINATOR)

    dy: uint256 = xp_reduced[convert(i, uint256)] - staticcall math.get_y_D(amp, i, [xp_reduced[0], xp_reduced[1]], D1, N_COINS)
    dy_0: uint256 = (xp[convert(i, uint256)] - new_y) * PRECISION // rates[convert(i, uint256)]  # w//o fees
    dy = unsafe_div((dy - 1) * PRECISION, rates[convert(i, uint256)])  # Withdraw less to account for rounding errors

    # calculate state price
    xp[convert(i, uint256)] = new_y

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
@pure
def _get_p(
    xp: uint256[N_COINS],
    amp: uint256,
    D: uint256,
) -> uint256:

    # dx_0 // dx_1 only, however can have any number of coins in pool
    ANN: uint256 = unsafe_mul(amp, N_COINS)
    Dr: uint256 = unsafe_div(D, pow_mod256(N_COINS, N_COINS))

    for i: uint256 in range(N_COINS_128):
        Dr = Dr * D // xp[i]

    # ANN * xp[0] // A_PRECISION
    xp0_A: uint256 = unsafe_div(ANN * xp[0], A_PRECISION)
    return 10**18 * (xp0_A + unsafe_div(Dr * xp[0], xp[1])) // (xp0_A + Dr)


@internal
def upkeep_oracles(xp: uint256[N_COINS], amp: uint256, D: uint256):
    """
    @notice Upkeeps price and D oracles.
    """
    ma_last_time_unpacked: uint256[2] = self.unpack_2(self.ma_last_time)
    last_prices_packed_current: uint256 = self.last_prices_packed
    last_prices_packed_new: uint256 = last_prices_packed_current

    spot_price: uint256 = self._get_p(xp, amp, D)

    # -------------------------- Upkeep price oracle -------------------------

    # Metapools are always 2-coin pools, so we care about idx=0 only:
    if spot_price != 0:

        # Update packed prices -----------------
        last_prices_packed_new = self.pack_2(
            min(spot_price, 2 * 10**18),  # <----- Cap spot value by 2.
            self._calc_moving_average(
                last_prices_packed_current,
                self.ma_exp_time,
                ma_last_time_unpacked[0],  # index 0 is ma_exp_time for prices
            )
        )

    self.last_prices_packed = last_prices_packed_new

    # ---------------------------- Upkeep D oracle ---------------------------

    self.last_D_packed = self.pack_2(
        D,
        self._calc_moving_average(
            self.last_D_packed,
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
        alpha: uint256 = staticcall math.exp(
            -convert(
                unsafe_div(unsafe_mul(unsafe_sub(block.timestamp, ma_last_time), 10**18), averaging_window), int256
            )
        )
        return unsafe_div(last_spot_value * (10**18 - alpha) + last_ema_value * alpha, 10**18)

    return last_ema_value


@view
@external
def last_price(i: uint256) -> uint256:
    assert i == 0  # dev: metapools do not have last_price indices greater than 0.
    return self.last_prices_packed & (2**128 - 1)


@view
@external
def ema_price(i: uint256) -> uint256:
    assert i == 0  # dev: metapools do not have ema_price indices greater than 0.
    return (self.last_prices_packed >> 128)


@external
@view
def get_p(i: uint256) -> uint256:
    """
    @notice Returns the AMM State price of token
    @dev if i = 0, it will return the state price of coin[1].
    @param i index of state price (0 for coin[1], 1 for coin[2], ...)
    @return uint256 The state price quoted by the AMM for coin[i+1]
    """
    assert i == 0  # dev: metapools do not have get_p indices greater than 0.

    amp: uint256 = self._A()
    xp: uint256[N_COINS] = self._xp_mem(
        self._stored_rates(), self._balances()
    )
    D: uint256 = staticcall math.get_D([xp[0], xp[1]], amp, N_COINS)
    return self._get_p(xp, amp, D)


@external
@view
@nonreentrant
def price_oracle(i: uint256) -> uint256:
    assert i == 0  # dev: metapools do not have price_oracle indices greater than 0.
    return self._calc_moving_average(
        self.last_prices_packed,
        self.ma_exp_time,
        self.ma_last_time & (2**128 - 1),
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


# ---------------------------- IERC20 Utils -----------------------------------


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
        _new_allowance: uint256 = _allowance - _value
        self.allowance[_from][msg.sender] = _new_allowance
        log Approval(owner=_from, spender=msg.sender, value=_new_allowance)

    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    """
    @notice Approve the passed address to transfer the specified amount of
            tokens on behalf of msg.sender
    @dev Beware that changing an allowance via this method brings the risk that
         someone may use both the old and new allowance by unfortunate transaction
         ordering: https://github.com//ethereum//EIPs//issues//20#issuecomment-263524729
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
        See https://eips.ethereum.org//EIPS//eip-2612.
    @dev Inspired by https://github.com//yearn//yearn-vaults//blob//main//contracts//Vault.vy#L753-L793
    @dev Supports smart contract wallets which implement ERC1271
        https://eips.ethereum.org//EIPS//eip-1271
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
        assert staticcall ERC1271(_owner).isValidSignature(digest, sig) == ERC1271_MAGIC_VAL
    else:
        assert ecrecover(digest, convert(_v, uint256), convert(_r, uint256), convert(_s, uint256)) == _owner

    self.allowance[_owner][_spender] = _value
    self.nonces[_owner] = unsafe_add(nonce, 1)

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
    @param j Index value of the coin to receive
    @param dy Amount of `j` being received after exchange
    @return Amount of `i` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dx(i, j, dy, self)


@view
@external
def get_dx_underlying(i: int128, j: int128, dy: uint256) -> uint256:
    """
    @notice Calculate the current input dx given output dy
    @dev Swap involves base pool tokens (either i or j should be 0);
         If not, this method reverts.
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
    @param dy Amount of `j` being received after exchange
    @return Amount of `i` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dx_underlying(i, j, dy, self)


@view
@external
def get_dy(i: int128, j: int128, dx: uint256) -> uint256:
    """
    @notice Calculate the current output dy given input dx
    @dev Index values can be found via the `coins` public getter method
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
    @param dx Amount of `i` being exchanged
    @return Amount of `j` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dy(i, j, dx, self)


@view
@external
def get_dy_underlying(i: int128, j: int128, dx: uint256) -> uint256:
    """
    @notice Calculate the current output dy given input dx
    @dev Swap involves base pool tokens (either i or j should be 0);
         If not, this method reverts.
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
    @param dx Amount of `i` being exchanged
    @return Amount of `j` predicted
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).get_dy_underlying(i, j, dx, self)


@view
@external
def calc_withdraw_one_coin(_burn_amount: uint256, i: int128) -> uint256:
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
    xp: uint256[N_COINS] = self._xp_mem(self._stored_rates(), self._balances())
    D: uint256 = staticcall math.get_D([xp[0], xp[1]], self._A(), N_COINS)
    # D is in the units similar to DAI (e.g. converted to precision 1e18)
    # When balanced, D = n * x_u - total virtual value of the portfolio
    return D * PRECISION // self.total_supply


@view
@external
def calc_token_amount(
    _amounts: uint256[N_COINS],
    _is_deposit: bool
) -> uint256:
    """
    @notice Calculate addition or reduction in token supply from a deposit or withdrawal
    @param _amounts Amount of each coin being deposited
    @param _is_deposit set True for deposits, False for withdrawals
    @return Expected amount of LP tokens received
    """
    return staticcall StableSwapViews(staticcall factory.views_implementation()).calc_token_amount(
        [_amounts[0], _amounts[1]],
        _is_deposit,
        self
    )


@view
@external
def A() -> uint256:
    return unsafe_div(self._A(), A_PRECISION)


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
    balances: uint256[N_COINS] = self._balances()
    return [balances[0], balances[1]]


@view
@external
def stored_rates() -> DynArray[uint256, MAX_COINS]:
    rates: uint256[N_COINS] = self._stored_rates()
    return [rates[0], rates[1]]


@view
@external
def dynamic_fee(i: int128, j: int128) -> uint256:
    """
    @notice Return the fee for swapping between `i` and `j`
    @param i Index value for the coin to send
    @param j Index value of the coin to receive
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
    @param _ma_exp_time Moving average window for the price oracle. It is time_in_seconds // ln(2).
    @param _D_ma_time Moving average window for the D oracle. It is time_in_seconds // ln(2).
    """
    assert msg.sender == staticcall factory.admin()  # dev: only owner
    assert unsafe_mul(_ma_exp_time, _D_ma_time) > 0  # dev: 0 in input values

    self.ma_exp_time = _ma_exp_time
    self.D_ma_time = _D_ma_time

    log SetNewMATime(ma_exp_time=_ma_exp_time, D_ma_time=_D_ma_time)
