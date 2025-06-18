# adapted from https://github.com/curvefi/stableswap-ng/blob/fd54b9a1a110d0e2e4f962583761d9e236b70967/contracts/main/CurveStableSwapMetaNG.vy

"""
@title CurveStableSwapNG
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2023 - all rights reserved
@notice Stableswap implementation for up to 8 coins with no rehypothecation,
        i.e. tokens are not deposited into other contracts. Supports only
        token pairs that are similarly priced. This contract also
        supports metapools (2-coin pools where the second coin is an LP token).
        The Pool contract also records exponential moving averages for coins
        1, 2 and 3 relative to coin 0.
@dev Supports:
@dev Asset Types:
        0. Basic ERC20 token with no additional features
        1. WETH - can we directly converted to/from ETH
        2. Oracle - token with rate oracle
        3. Rebasing - token with rebase (e.g. stETH)
     Supports:
        1. ERC20 support for return True/revert, return True/False, return None
        2. ERC20 tokens can have arbitrary decimals (<=18).
        3. ERC20 tokens that rebase (either positive or fee on transfer)
        4. ERC20 tokens that have a rate oracle (e.g. wstETH, cbETH, sDAI, etc.)
     Additional features include:
        1. Support for rebasing tokens: but this disables
           `exchange_received`.
        2. Support for ERC20 tokens with rate oracles (e.g. wstETH, sDAI)
           Note: Oracle precision _must_ be 10**18.
        3. Support for ETH/WETH transfers
        4. Adds oracles based on AMM State Price (and _not_ last traded price).
        5. Adds exchanging tokens with callbacks that allows for:
            a. reduced ERC20 token transfers in zap contracts
            b. swaps without transferFrom (no need for token approvals)
        6. Adds feature: `exchange_received`, which is inspired
           by Uniswap V2: swaps that expect an ERC20 transfer to have occurred
           prior to executing the swap.
           Note: a. If pool contains rebasing tokens and one of the `asset_types` is 3 (Rebasing)
                    then calling `exchange_received` will REVERT.
                 b. If pool contains rebasing token and `asset_types` does not contain 3 (Rebasing)
                    then this is an incorrect implementation and rebases can be
                    stolen.
        7. Adds `get_dx`: Similar to `get_dy` which returns an expected output
           of coin[j] for given `dx` amount of coin[i], `get_dx` returns expected
           input of coin[i] for an output amount of coin[j].
"""

from ethereum.ercs import IERC20

implements: IERC20

# ------------------------------- Interfaces ---------------------------------

interface Factory:
    def get_fee_receiver() -> address: view
    def admin() -> address: view
    def views_implementation() -> address: view

interface WETH:
    def deposit(): payable
    def withdraw(_amount: uint256): nonpayable

interface ERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes32: view

interface StableSwapViews:
    def get_dx(i: int128, j: int128, dy: uint256, pool: address) -> uint256: view
    def get_dy(i: int128, j: int128, dy: uint256, pool: address) -> uint256: view
    def calc_token_amount(
        _amounts: DynArray[uint256, MAX_COINS],
        _is_deposit: bool,
        _pool: address
    ) -> uint256: view

interface StableSwap2:
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256): nonpayable

interface StableSwap3:
    def add_liquidity(amounts: uint256[3], min_mint_amount: uint256): nonpayable

interface StableSwap4:
    def add_liquidity(amounts: uint256[4], min_mint_amount: uint256): nonpayable

interface StableSwap:
    def remove_liquidity_one_coin(_token_amount: uint256, i: int128, min_amount: uint256): nonpayable
    def exchange(i: int128, j: int128, dx: uint256, min_dy: uint256): nonpayable
    def get_virtual_price() -> uint256: view

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


MAX_COINS: constant(uint256) = 8  # max coins is 8 in the factory
MAX_METAPOOL_COIN_INDEX: constant(int128) = 1

# ---------------------------- Pool Variables --------------------------------

WETH20: immutable(address)
N_COINS: public(constant(uint256)) = 2
N_COINS_128: constant(int128) = 2
PRECISION: constant(uint256) = 10 ** 18

# To denote that it is a plain pool:
BASE_POOL: public(immutable(address))
BASE_N_COINS: public(immutable(uint256))
BASE_COINS: public(immutable(DynArray[address, MAX_COINS]))

factory: public(immutable(Factory))
coins: public(immutable(DynArray[address, MAX_COINS]))
stored_balances: DynArray[uint256, MAX_COINS]
fee: public(uint256)  # fee * 1e10
asset_types: public(immutable(DynArray[uint8, MAX_COINS]))

FEE_DENOMINATOR: constant(uint256) = 10 ** 10

# ---------------------- Pool Amplification Parameters -----------------------

A_PRECISION: constant(uint256) = 100
MAX_A: constant(uint256) = 10 ** 6
MAX_A_CHANGE: constant(uint256) = 10

initial_A: public(uint256)
future_A: public(uint256)
initial_A_time: public(uint256)
future_A_time: public(uint256)

# ---------------------------- Admin Variables -------------------------------

ADMIN_FEE: constant(uint256) = 5000000000
MAX_FEE: constant(uint256) = 5 * 10 ** 9
MIN_RAMP_TIME: constant(uint256) = 86400
admin_balances: public(DynArray[uint256, MAX_COINS])

# ----------------------- Oracle Specific vars -------------------------------

rate_multipliers: immutable(DynArray[uint256, MAX_COINS])
# [bytes4 method_id][bytes8 <empty>][bytes20 oracle]
oracles: DynArray[uint256, MAX_COINS]

last_prices_packed: public(DynArray[uint256, MAX_COINS])  #  packing: last_price, ma_price
ma_exp_time: public(uint256)
ma_last_time: public(uint256)

# shift(2**32 - 1, 224)
ORACLE_BIT_MASK: constant(uint256) = (2**32 - 1) * 256**28

# --------------------------- ERC20 Specific Vars ----------------------------

name: public(immutable(String[64]))
symbol: public(immutable(String[32]))
decimals: public(constant(uint8)) = 18
version: public(constant(String[8])) = "v7.0.0"

balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])
totalSupply: public(uint256)
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
    _ma_exp_time: uint256,
    _weth: address,
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
    @param _coins List of addresses of the coins being used in the pool.
    @param _A Amplification co-efficient - a lower value here means
              less tolerance for imbalance within the pool's assets.
              Suggested values include:
               * Uncollateralized algorithmic stablecoins: 5-10
               * Non-redeemable, collateralized assets: 100
               * Redeemable assets: 200-400
    @param _fee Trade fee, given as an integer with 1e10 precision. The
                the maximum is 1% (100000000).
                50% of the fee is distributed to veCRV holders.
    @param _ma_exp_time Averaging window of oracle. Set as time_in_seconds / ln(2)
                        Example: for 10 minute EMA, _ma_exp_time is 600 / ln(2) ~= 866
    @param _asset_types Array of uint8 representing tokens in pool
    @param _method_ids Array of first four bytes of the Keccak-256 hash of the function signatures
                       of the oracle addresses that gives rate oracles.
                       Calculated as: keccak(text=event_signature.replace(" ", ""))[:4]
    @param _oracles Array of rate oracle addresses.
    """

    WETH20 = _weth
    BASE_POOL = _base_pool
    BASE_COINS = _base_coins
    BASE_N_COINS = len(_base_coins)
    coins = _coins
    rate_multipliers = _rate_multipliers
    asset_types = _asset_types  # contains asset types for all pool tokens including base pool tokens

    for i: uint256 in range(MAX_COINS):
        if i < BASE_N_COINS:
            # Approval needed for add_liquidity operation on base pool in _exchange_underlying
            extcall IERC20(_base_coins[i]).approve(BASE_POOL, max_value(uint256))

    self.last_prices_packed.append(self.pack_prices(10**18, 10**18))

    # ----------------- Parameters independent of pool type ------------------

    factory = Factory(msg.sender)

    A: uint256 = _A * A_PRECISION
    self.initial_A = A
    self.future_A = A
    self.fee = _fee

    assert _ma_exp_time != 0
    self.ma_exp_time = _ma_exp_time
    self.ma_last_time = block.timestamp

    for i: int128 in range(N_COINS_128):

        # Enforce native token as coin[0]
        if _coins[i] == WETH20:
            assert i == 0 # dev: "ETH must be at index 0"

        self.oracles.append(convert(_method_ids[i], uint256) * 2**224 | convert(_oracles[i], uint256))
        self.admin_balances.append(0)  # <--- this initialises storage for admin balances  # TODO: check if this is needed?

    # --------------------------- ERC20 stuff ----------------------------

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


@payable
@external
def __default__():
    if msg.value > 0:
        assert WETH20 in coins


@internal
def _transfer_in(
    coin_idx: int128,
    dx: uint256,
    dy: uint256,
    mvalue: uint256,
    callbacker: address,
    callback_sig: bytes32,
    sender: address,
    receiver: address,
    use_eth: bool,
    expect_optimistic_transfer: bool,
) -> uint256:
    """
    @notice Contains all logic to handle ERC20 or native token transfers
    @dev The callback sig must have the following args:
            sender: address
            receiver: address
            coin: address
            dx: uint256
            dy: uint256
         The `dy` that the pool enforces is actually min_dy.
         Callback only occurs for `exchange_extended`.
         Callback cannot happen for `_use_eth` = True.
    @dev If callback_sig is empty, `_transfer_in` does a transferFrom.
    @params _coin address of the coin to transfer in.
    @params dx amount of `_coin` to transfer into the pool.
    @params dy amount of `_coin` to transfer out of the pool.
    @params mvalue msg.value if the transfer is ETH, 0 otherwise.
    @params callbacker address to call `callback_sig` on.
    @params callback_sig signature of the callback function.
    @params sender address to transfer `_coin` from.
    @params receiver address to transfer `_coin` to.
    @params use_eth True if the transfer is ETH, False otherwise.
    @params expect_optimistic_transfer True if contract expects an optimistic coin transfer
    """
    _dx: uint256 = staticcall IERC20(coins[coin_idx]).balanceOf(self)
    _incoming_coin_asset_type: uint8 = asset_types[coin_idx]

    # ------------------------- Handle Transfers -----------------------------

    if use_eth and coins[coin_idx] == WETH20:

        _dx = mvalue
        extcall WETH(WETH20).deposit(value=dx)

    elif expect_optimistic_transfer:

        assert _incoming_coin_asset_type != 3 # dev: "exchange_received not allowed if incoming token is rebasing"
        _dx = staticcall IERC20(coins[coin_idx]).balanceOf(self) - self.stored_balances[coin_idx]

    elif callback_sig != empty(bytes32):

        raw_call(
                callbacker,
                concat(
                    slice(callback_sig, 0, 4),
                    abi_encode(sender, receiver, coins[coin_idx], dx, dy)
                )
            )

        _dx = staticcall IERC20(coins[coin_idx]).balanceOf(self) - _dx

    else:

        assert extcall IERC20(coins[coin_idx]).transferFrom(
            sender, self, dx, default_return_value=True
        )

        _dx = staticcall IERC20(coins[coin_idx]).balanceOf(self) - _dx

    # --------------------------- Check Transfer -----------------------------

    if _incoming_coin_asset_type == 3:
        assert _dx > 0 # dev: "Pool did not receive tokens for swap"  # TODO: Check this!!
    else:
        assert dx == _dx # dev: "Pool did not receive tokens for swap"

    # ----------------------- Update Stored Balances -------------------------

    self.stored_balances[coin_idx] += _dx

    return _dx


@internal
def _transfer_out(
    _coin_idx: int128, _amount: uint256, use_eth: bool, receiver: address
):
    """
    @notice Transfer a single token from the pool to receiver.
    @dev This function is called by `remove_liquidity` and
         `remove_liquidity_one` and `_exchange` methods.
    @params _coin Address of the token to transfer out
    @params _amount Amount of token to transfer out
    @params use_eth Whether to transfer ETH or not
    @params receiver Address to send the tokens to
    """

    # ------------------------- Handle Transfers -----------------------------

    if use_eth and coins[_coin_idx] == WETH20:

        extcall WETH(WETH20).withdraw(_amount)
        raw_call(receiver, b"", value=_amount)

    else:

        assert extcall IERC20(coins[_coin_idx]).transfer(
            receiver, _amount, default_return_value=True
        )

    # ----------------------- Update Stored Balances -------------------------

    self.stored_balances[_coin_idx] -= _amount


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
    rates: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    if BASE_POOL != empty(address):
        rates = [rate_multipliers[0], staticcall StableSwap(BASE_POOL).get_virtual_price()]
    else:
        rates = rate_multipliers

    oracles: DynArray[uint256, MAX_COINS] = self.oracles

    for i: int128 in range(N_COINS_128):

        if oracles[i] == 0:
            continue

        # NOTE: assumed that response is of precision 10**18
        response: Bytes[32] = raw_call(
            convert(oracles[i] % 2**160, address),
            abi_encode(oracles[i] & ORACLE_BIT_MASK),
            max_outsize=32,
            is_static_call=True,
        )

        assert len(response) != 0
        rates[i] = rates[i] * convert(response, uint256) // PRECISION

    return rates


@view
@internal
def _balances() -> DynArray[uint256, MAX_COINS]:
    """
    @notice Calculates the pool's balances _excluding_ the admin's balances.
    @dev This method ensures LPs keep all rebases and admin only claims swap fees.
    """
    result: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    for i: int128 in range(N_COINS_128):
        result.append(staticcall IERC20(coins[i]).balanceOf(self) - self.admin_balances[i])

    return result


# -------------------------- AMM Main Functions ------------------------------


@payable
@external
def exchange(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _use_eth: bool = False,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins
    @dev Index values can be found via the `coins` public getter method
         Allows for native token swaps (e.g. ETH <> whatever)
         If native token is not in coin list and msg.value > 0, swap will revert
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @return Actual amount of `j` received
    """
    return self._exchange(
        msg.sender,
        msg.value,
        i,
        j,
        _dx,
        _min_dy,
        _use_eth,
        _receiver,
        empty(address),
        empty(bytes32),
        False
    )


@external
def exchange_extended(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _use_eth: bool,
    _sender: address,
    _receiver: address,
    _cb: bytes32
) -> uint256:
    """
    @notice Perform an exchange between two coins after a callback
    @dev Index values can be found via the `coins` public getter method
         Not payable (does not accept eth). Users of this method are dex aggregators,
         arbitrageurs, or other users who do not wish to grant approvals to the contract.
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @return Actual amount of `j` received
    """
    assert _cb != empty(bytes32)  # dev: No callback specified
    return self._exchange(
        _sender,
        0,  # mvalue is zero here
        i,
        j,
        _dx,
        _min_dy,
        _use_eth,
        _receiver,
        msg.sender,  # <---------------------------- callbacker is msg.sender.
        _cb,
        False
    )


@external
def exchange_received(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _use_eth: bool = False,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two coins without transferring token in
    @dev The contract swaps tokens based on a change in balance of coin[i]. The
         dx = staticcall IERC20(coin[i]).balanceOf(self) - self.stored_balances[i]. Users of
         this method are dex aggregators, arbitrageurs, or other users who do not
         wish to grant approvals to the contract: they would instead send tokens
         directly to the contract and call `exchange_received`.
         The method is non-payable: does not accept native token.
    @param i Index value for the coin to send
    @param j Index valie of the coin to recieve
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @return Actual amount of `j` received
    """
    return self._exchange(
        msg.sender,
        0,
        i,
        j,
        _dx,
        _min_dy,
        _use_eth,
        _receiver,
        empty(address),
        empty(bytes32),
        True,  # <--------------------------------------- swap optimistically.
    )


@external
def exchange_underlying(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Perform an exchange between two underlying coins
    @dev Even if _use_eth is in the abi, the method does not accept native token
    @param i Index value for the underlying coin to send
    @param j Index value of the underlying coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
    @return Actual amount of `j` received
    """
    return self._exchange_underlying(
        msg.sender,
        i,
        j,
        _dx,
        _min_dy,
        _receiver,
        empty(address),
        empty(bytes32),
        False
    )


@external
def exchange_underlying_extended(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address,
    _cb: bytes32
) -> uint256:
    """
    @notice Perform an exchange between two underlying coins
    @dev Even if _use_eth is in the abi, the method does not accept native token
    @param i Index value for the underlying coin to send
    @param j Index value of the underlying coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
    @return Actual amount of `j` received
    """
    assert _cb != empty(bytes32)  # dev: no callback specified
    return self._exchange_underlying(
        msg.sender,
        i,
        j,
        _dx,
        _min_dy,
        _receiver,
        msg.sender,
        _cb,
        False
    )


@external
def exchange_underlying_received(
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    _receiver: address,
) -> uint256:
    """
    @notice Perform an exchange between two underlying coins
    @dev Even if _use_eth is in the abi, the method does not accept native token
    @param i Index value for the underlying coin to send
    @param j Index value of the underlying coin to receive
    @param _dx Amount of `i` being exchanged
    @param _min_dy Minimum amount of `j` to receive
    @param _receiver Address that receives `j`
    @return Actual amount of `j` received
    """
    return self._exchange_underlying(
        msg.sender,
        i,
        j,
        _dx,
        _min_dy,
        _receiver,
        empty(address),
        empty(bytes32),
        True
    )


@payable
@external
def add_liquidity(
    _amounts: DynArray[uint256, MAX_COINS],
    _min_mint_amount: uint256,
    _use_eth: bool = False,
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

    total_supply: uint256 = self.totalSupply
    new_balances: DynArray[uint256, MAX_COINS] = old_balances

    # -------------------------- Do Transfers In -----------------------------

    for i: int128 in range(N_COINS_128):

        if _amounts[i] > 0:

            new_balances[i] += self._transfer_in(
                i,
                _amounts[i],
                0,
                msg.value,
                empty(address),
                empty(bytes32),
                msg.sender,
                empty(address),
                _use_eth,
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

        # Only account for fees if we are not the first to deposit
        base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
        for i: int128 in range(N_COINS_128):

            ideal_balance: uint256 = D1 * old_balances[i] // D0
            difference: uint256 = 0
            new_balance: uint256 = new_balances[i]
            if ideal_balance > new_balance:
                difference = ideal_balance - new_balance
            else:
                difference = new_balance - ideal_balance

            fees[i] = base_fee * difference // FEE_DENOMINATOR
            self.admin_balances[i] += fees[i] * ADMIN_FEE // FEE_DENOMINATOR
            new_balances[i] -= fees[i]

        xp: DynArray[uint256, MAX_COINS] = self._xp_mem(rates, new_balances)
        D2: uint256 = self.get_D(xp, amp)
        mint_amount = total_supply * (D2 - D0) // D0
        self.save_p(xp, amp, D2)

    else:

        mint_amount = D1  # Take the dust if there was any

    assert mint_amount >= _min_mint_amount # dev: "Slippage screwed you"

    # Mint pool tokens
    total_supply += mint_amount
    self.balanceOf[_receiver] += mint_amount
    self.totalSupply = total_supply
    log Transfer(sender=empty(address), receiver=_receiver, value=mint_amount)

    log AddLiquidity(provider=msg.sender, token_amounts=_amounts, fees=fees, invariant=D1, token_supply=total_supply)

    return mint_amount


@external
def remove_liquidity_one_coin(
    _burn_amount: uint256,
    i: int128,
    _min_received: uint256,
    _use_eth: bool = False,
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
    dy: uint256 = 0
    fee: uint256 = 0
    p: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    dy, fee, p = self._calc_withdraw_one_coin(_burn_amount, i)
    assert dy >= _min_received # dev: "Not enough coins removed"

    self.admin_balances[i] += fee * ADMIN_FEE // FEE_DENOMINATOR

    self._burnFrom(msg.sender, _burn_amount)

    log Transfer(sender=msg.sender, receiver=empty(address), value=_burn_amount)

    self._transfer_out(i, dy, _use_eth, _receiver)

    log RemoveLiquidityOne(provider=msg.sender, token_id=i, token_amount=_burn_amount, coin_amount=dy, token_supply=self.totalSupply)

    self.save_p_from_price(p)

    return dy


@external
def remove_liquidity_imbalance(
    _amounts: DynArray[uint256, MAX_COINS],
    _max_burn_amount: uint256,
    _use_eth: bool = False,
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

    for i: int128 in range(N_COINS_128):

        if _amounts[i] != 0:
            new_balances[i] -= _amounts[i]
            self._transfer_out(i, _amounts[i], _use_eth, _receiver)

    D1: uint256 = self.get_D_mem(rates, new_balances, amp)
    fees: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))

    for i: int128 in range(N_COINS_128):

        ideal_balance: uint256 = D1 * old_balances[i] // D0
        difference: uint256 = 0
        new_balance: uint256 = new_balances[i]
        if ideal_balance > new_balance:
            difference = ideal_balance - new_balance
        else:
            difference = new_balance - ideal_balance

        fees[i] = base_fee * difference // FEE_DENOMINATOR
        self.admin_balances[i] += fees[i] * ADMIN_FEE // FEE_DENOMINATOR
        new_balances[i] -= fees[i]

    D2: uint256 = self.get_D_mem(rates, new_balances, amp)

    self.save_p(new_balances, amp, D2)

    total_supply: uint256 = self.totalSupply
    burn_amount: uint256 = ((D0 - D2) * total_supply // D0) + 1
    assert burn_amount > 1  # dev: zero tokens burned
    assert burn_amount <= _max_burn_amount # dev: "Slippage screwed you"

    self._burnFrom(msg.sender, burn_amount)

    log RemoveLiquidityImbalance(provider=msg.sender, token_amounts=_amounts, fees=fees, invariant=D1, token_supply=total_supply)

    return burn_amount


@external
def remove_liquidity(
    _burn_amount: uint256,
    _min_amounts: DynArray[uint256, MAX_COINS],
    _use_eth: bool = False,
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
    total_supply: uint256 = self.totalSupply
    amounts: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    balances: DynArray[uint256, MAX_COINS] = self._balances()

    for i: int128 in range(N_COINS_128):

        value: uint256 = balances[i] * _burn_amount // total_supply
        assert value >= _min_amounts[i] # dev: "Withdrawal resulted in fewer coins than expected"
        amounts[i] = value
        self._transfer_out(i, value, _use_eth, _receiver)

    self._burnFrom(msg.sender, _burn_amount)  # dev: insufficient funds

    log RemoveLiquidity(provider=msg.sender, token_amounts=amounts, fees=empty(DynArray[uint256, MAX_COINS]), token_supply=total_supply) # TODO: check this!

    # Withdraw admin fees if _claim_admin_fees is set to True. Helps automate.
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


@internal
def __exchange(
    dx: uint256,
    x: uint256,
    _xp: DynArray[uint256, MAX_COINS],
    rates: DynArray[uint256, MAX_COINS],
    i: int128,
    j: int128,
) -> uint256:

    amp: uint256 = self._A()
    D: uint256 = self.get_D(_xp, amp)
    y: uint256 = self.get_y(i, j, x, _xp, amp, D)

    dy: uint256 = _xp[j] - y - 1  # -1 just in case there were some rounding errors
    dy_fee: uint256 = dy * self.fee // FEE_DENOMINATOR

    # Convert all to real units
    dy = (dy - dy_fee) * PRECISION // rates[j]

    self.admin_balances[j] += (
        dy_fee * ADMIN_FEE // FEE_DENOMINATOR
    ) * PRECISION // rates[j]

    # Calculate and store state prices:
    xp: DynArray[uint256, MAX_COINS] = _xp
    xp[i] = x
    xp[j] = y
    # D is not changed because we did not apply a fee
    self.save_p(xp, amp, D)

    return dy


@internal
def _exchange(
    sender: address,
    mvalue: uint256,
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    use_eth: bool,
    receiver: address,
    callbacker: address,
    callback_sig: bytes32,
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
        _min_dy,
        mvalue,
        callbacker,
        callback_sig,
        sender,
        receiver,
        use_eth,
        expect_optimistic_transfer
    )

    # ------------------------------- Exchange -------------------------------

    x: uint256 = xp[i] + dx * rates[i] // PRECISION
    dy: uint256 = self.__exchange(dx, x, xp, rates, i, j)
    assert dy >= _min_dy # dev: "Exchange resulted in fewer coins than expected"

    # --------------------------- Do Transfer out ----------------------------

    self._transfer_out(j, dy, use_eth, receiver)

    # ------------------------------------------------------------------------

    log TokenExchange(buyer=msg.sender, sold_id=i, tokens_sold=_dx, bought_id=j, tokens_bought=dy)

    return dy


@internal
def _exchange_underlying(
    sender: address,
    i: int128,
    j: int128,
    _dx: uint256,
    _min_dy: uint256,
    receiver: address,
    callbacker: address,
    callback_sig: bytes32,
    expect_optimistic_transfer: bool = False
) -> uint256:

    assert BASE_POOL != empty(address)  # dev: pool is not a metapool

    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    old_balances: DynArray[uint256, MAX_COINS] = self._balances()
    xp: DynArray[uint256, MAX_COINS]  = self._xp_mem(rates, old_balances)

    dy: uint256 = 0
    base_i: int128 = 0
    base_j: int128 = 0
    meta_i: int128 = 0
    meta_j: int128 = 0
    x: uint256 = 0
    input_coin: address = empty(address)
    output_coin: address = empty(address)

    if i == 0:
        input_coin = coins[0]
    else:
        base_i = i - MAX_METAPOOL_COIN_INDEX  # if i == 1, this reverts
        meta_i = 1
        input_coin = BASE_COINS[base_i]
    if j == 0:
        output_coin = coins[0]
    else:
        base_j = j - MAX_METAPOOL_COIN_INDEX  # if j == 1, this reverts
        meta_j = 1
        output_coin = BASE_COINS[base_j]

    # --------------------------- Do Transfer in -----------------------------

    dx_w_fee: uint256 = 0

    # for exchange_underlying, optimistic transfers need to be handled differently
    if expect_optimistic_transfer:

        assert asset_types[i] != 3  # dev: rebasing coins not supported

        # This branch is never reached for rebasing tokens
        if input_coin == BASE_COINS[base_i]:
            # we expect base_coin's balance to be 0. So swap whatever base_coin's
            # balance the pool has:
            dx_w_fee = staticcall IERC20(input_coin).balanceOf(self)
        else:
            dx_w_fee = staticcall IERC20(input_coin).balanceOf(self) - self.stored_balances[meta_i]
            assert dx_w_fee == _dx
            self.stored_balances[meta_i] += dx_w_fee

        dx_w_fee = staticcall IERC20(input_coin).balanceOf(self) - _dx

    else:

        dx_w_fee = self._transfer_in(
            i,
            _dx,
            _min_dy,
            0,  # msg.value is always 0 for exchange_underlying
            callbacker,
            callback_sig,
            sender,
            receiver,
            False,  # use_eth = False
            False,  # expect_optimistic_transfer = False
        )

    # ------------------------------------------------------------------------

    if i == 0 or j == 0:  # meta swap

        if i == 0:

            x = xp[i] + dx_w_fee * rates[i] // PRECISION

        else:

            dx_w_fee = self._meta_add_liquidity(dx_w_fee, base_i)
            x = dx_w_fee * rates[MAX_METAPOOL_COIN_INDEX] // PRECISION
            x += xp[MAX_METAPOOL_COIN_INDEX]

        dy = self.__exchange(dx_w_fee, x, xp, rates, meta_i, meta_j)

        # Withdraw from the base pool if needed
        if j > 0:
            out_amount: uint256 = staticcall IERC20(output_coin).balanceOf(self)
            extcall StableSwap(BASE_POOL).remove_liquidity_one_coin(dy, base_j, 0)
            dy = staticcall IERC20(output_coin).balanceOf(self) - out_amount

        assert dy >= _min_dy

        # Adjust stored balances:
        self.stored_balances[meta_j] -= dy

    else:  # base pool swap (user should swap at base pool for better gas)

        dy = staticcall IERC20(output_coin).balanceOf(self)
        extcall StableSwap(BASE_POOL).exchange(base_i, base_j, dx_w_fee, _min_dy)
        dy = staticcall IERC20(output_coin).balanceOf(self) - dy

    # --------------------------- Do Transfer out ----------------------------

    assert extcall IERC20(output_coin).transfer(receiver, dy, default_return_value=True)

    # ------------------------------------------------------------------------

    log TokenExchangeUnderlying(buyer=sender, sold_id=i, tokens_sold=_dx, bought_id=j, tokens_bought=dy) # TODO: check this!

    return dy


@internal
def _meta_add_liquidity(dx: uint256, base_i: int128) -> uint256:

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

    else:

        base_inputs: uint256[4] = empty(uint256[4])
        base_inputs[base_i] = dx
        extcall StableSwap4(BASE_POOL).add_liquidity(base_inputs, 0)

    return staticcall IERC20(coin_i).balanceOf(self) - x


@internal
def _withdraw_admin_fees():

    fee_receiver: address = staticcall factory.get_fee_receiver()
    assert fee_receiver != empty(address)  # dev: fee receiver not set

    for i: int128 in range(N_COINS_128):
        admin_balance: uint256 = self.admin_balances[i]
        if admin_balance > 0:
            self._transfer_out(i, admin_balance, False, fee_receiver)
            self.admin_balances[i] = 0


# --------------------------- AMM Math Functions -----------------------------


@view
@internal
def get_y(
    i: int128,
    j: int128,
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
    if _D == 0:
        amp = self._A()
        D = self.get_D(xp, amp)
    S_: uint256 = 0
    _x: uint256 = 0
    y_prev: uint256 = 0
    c: uint256 = D
    Ann: uint256 = amp * N_COINS

    for _i: int128 in range(N_COINS_128):

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

    for _i: int128 in range(255):
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


@pure
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

    for i: uint256  in range(255):
        D_P = D * D // _xp[0] * D // _xp[1] // pow_mod256(N_COINS, N_COINS)
        Dprev = D
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

    for _i: int128 in range(N_COINS_128):

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


@pure
@internal
def _xp_mem(
    _rates: DynArray[uint256, MAX_COINS],
    _balances: DynArray[uint256, MAX_COINS]
) -> DynArray[uint256, MAX_COINS]:

    result: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    for i: int128 in range(N_COINS_128):

        result[i] = _rates[i] * _balances[i] // PRECISION

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
    i: int128
) -> (
    uint256,
    uint256,
    DynArray[uint256, MAX_COINS]
):
    # First, need to calculate
    # * Get current D
    # * Solve Eqn against y_i for D - _token_amount
    amp: uint256 = self._A()
    rates: DynArray[uint256, MAX_COINS] = self._stored_rates()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(rates, self._balances())
    D0: uint256 = self.get_D(xp, amp)

    total_supply: uint256 = self.totalSupply
    D1: uint256 = D0 - _burn_amount * D0 // total_supply
    new_y: uint256 = self.get_y_D(amp, i, xp, D1)

    base_fee: uint256 = self.fee * N_COINS // (4 * (N_COINS - 1))
    xp_reduced: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    for j: int128 in range(N_COINS_128):

        dx_expected: uint256 = 0
        xp_j: uint256 = xp[j]
        if j == i:
            dx_expected = xp_j * D1 // D0 - new_y
        else:
            dx_expected = xp_j - xp_j * D1 // D0
        xp_reduced[j] = xp_j - base_fee * dx_expected // FEE_DENOMINATOR

    dy: uint256 = xp_reduced[i] - self.get_y_D(amp, i, xp_reduced, D1)
    dy_0: uint256 = (xp[i] - new_y) * PRECISION // rates[i]  # w/o fees
    dy = (dy - 1) * PRECISION // rates[i]  # Withdraw less to account for rounding errors

    xp[i] = new_y
    last_p: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    if new_y > 0:
        last_p = self._get_p(xp, amp, D1)

    return dy, dy_0 - dy, last_p


# -------------------------- AMM Price Methods -------------------------------

@pure
@internal
def pack_prices(p1: uint256, p2: uint256) -> uint256:
    assert p1 < 2**128
    assert p2 < 2**128
    return p1 | (p2 << 128)


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

    for i: int128 in range(N_COINS_128):
        Dr = Dr * D // xp[i]

    p: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    xp0_A: uint256 = ANN * xp[0] // A_PRECISION
    p.append(10**18 * (xp0_A + Dr * xp[0] // xp[1]) // (xp0_A + Dr))

    return p


@internal
def save_p_from_price(last_prices: DynArray[uint256, MAX_COINS]):
    """
    Saves current price and its EMA
    """
    if last_prices[0] != 0:

        # Upate packed prices -----------------
        self.last_prices_packed[0] = self.pack_prices(last_prices[0], self._ma_price())

        # Update ma_last_time ------------------
        if self.ma_last_time < block.timestamp:
            self.ma_last_time = block.timestamp


@internal
def save_p(xp: DynArray[uint256, MAX_COINS], amp: uint256, D: uint256):
    """
    Saves current price and its EMA
    """
    self.save_p_from_price(self._get_p(xp, amp, D))


@internal
@view
def _ma_price() -> uint256:
    ma_last_time: uint256 = self.ma_last_time

    pp: uint256 = self.last_prices_packed[0]
    last_price: uint256 = pp & (2**128 - 1)
    last_ema_price: uint256 = (pp >> 128)

    if ma_last_time < block.timestamp:
        alpha: uint256 = self.exp(- convert((block.timestamp - ma_last_time) * 10**18 // self.ma_exp_time, int256))
        return (last_price * (10**18 - alpha) + last_ema_price * alpha) // 10**18

    else:
        return last_ema_price


@view
@external
def last_price(i: uint256) -> uint256:
    return self.last_prices_packed[0] & (2**128 - 1)


@view
@external
def ema_price(i: uint256) -> uint256:
    return (self.last_prices_packed[0] >> 128)


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
    return self._get_p(xp, amp, D)[0]


@external
@view
def price_oracle(i: uint256) -> uint256:
    return self._ma_price()


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
        return empty(uint256)

    # When the result is "> (2 ** 255 - 1) / 1e18" we cannot represent it as a signed integer.
    # This happens when "x >= floor(log((2 ** 255 - 1) / 1e18) * 1e18) ~ 135".
    assert x < 135305999368893231589 # dev: "wad_exp overflow"

    # `x` is now in the range "(-42, 136) * 1e18". Convert to "(-42, 136) * 2 ** 96" for higher
    # intermediate precision and a binary base. This base conversion is a multiplication with
    # "1e18 / 2 ** 96 = 5 ** 18 / 2 ** 78".
    value = unsafe_div(x << 78, 5 ** 18)

    # Reduce the range of `x` to "(-½ ln 2, ½ ln 2) * 2 ** 96" by factoring out powers of two
    # so that "exp(x) = exp(x') * 2 ** k", where `k` is a signer integer. Solving this gives
    # "k = round(x / log(2))" and "x' = x - k * log(2)". Thus, `k` is in the range "[-61, 195]".
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
    #   - the factor "1e18 / 2 ** 96" for the base conversion.
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

    self.totalSupply -= _burn_amount
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
        assert staticcall ERC1271(_owner).isValidSignature(digest, sig) == ERC1271_MAGIC_VAL
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
def get_virtual_price() -> uint256:
    """
    @notice The current virtual price of the pool LP token
    @dev Useful for calculating profits
    @return LP token virtual price normalized to 1e18
    """
    amp: uint256 = self._A()
    xp: DynArray[uint256, MAX_COINS] = self._xp_mem(self._stored_rates(), self._balances())
    D: uint256 = self.get_D(xp, amp)
    # D is in the units similar to DAI (e.g. converted to precision 1e18)
    # When balanced, D = n * x_u - total virtual value of the portfolio
    return D * PRECISION // self.totalSupply


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
    views: address = staticcall factory.views_implementation()
    return staticcall StableSwapViews(views).calc_token_amount(_amounts, _is_deposit, self)


@view
@external
def admin_fee() -> uint256:
    return ADMIN_FEE


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
def oracle(_idx: uint256) -> address:
    return convert(self.oracles[0] % 2**160, address)


@view
@external
def stored_rates(i: uint256) -> uint256:
    return self._stored_rates()[i]


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
def apply_new_fee(_new_fee: uint256):

    assert msg.sender == staticcall factory.admin()
    assert _new_fee <= MAX_FEE
    self.fee = _new_fee

    log ApplyNewFee(fee=_new_fee)


@external
def set_ma_exp_time(_ma_exp_time: uint256):
    """
    @notice Set the moving average window of the price oracle.
    @param _ma_exp_time Moving average window. It is time_in_seconds // ln(2)
    """
    assert msg.sender == staticcall factory.admin()  # dev: only owner
    assert _ma_exp_time != 0

    self.ma_exp_time = _ma_exp_time
