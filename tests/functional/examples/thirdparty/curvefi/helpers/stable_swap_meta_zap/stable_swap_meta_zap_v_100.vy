# pragma version >=0.4.2

"""
@title CurveMetaZap
@custom:version 1.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2021 - all rights reserved
@notice A generalised zap contract for Stableswap-ng metapools where the base pool
        is a Stableswap-ng implementation as well.
@dev Contract assumes Metapools have 2 coins.
"""

version: public(constant(String[8])) = "1.0.0"


interface IERC20:
    def transfer(receiver: address, amount: uint256): nonpayable
    def transferFrom(_sender: address, receiver: address, amount: uint256): nonpayable
    def approve(spender: address, amount: uint256): nonpayable
    def decimals() -> uint256: view
    def balanceOf(owner: address) -> uint256: view

interface StableSwapMetaNG:
    def add_liquidity(
        amounts: uint256[META_N_COINS],
        min_mint_amount: uint256,
        receiver: address
    ) -> uint256: nonpayable
    def remove_liquidity(
        amount: uint256,
        min_amounts: uint256[META_N_COINS]
    ) -> uint256[META_N_COINS]: nonpayable
    def remove_liquidity_one_coin(
        token_amount: uint256,
        i: int128,
        min_amount: uint256,
        receiver: address
    ) -> uint256: nonpayable
    def remove_liquidity_imbalance(
        amounts: uint256[META_N_COINS],
        max_burn_amount: uint256
    ) -> uint256: nonpayable
    def calc_withdraw_one_coin(token_amount: uint256, i: int128) -> uint256: view
    def calc_token_amount(amounts: uint256[META_N_COINS], deposit: bool) -> uint256: view
    def coins(i: uint256) -> address: view
    def BASE_POOL() -> address: view
    def BASE_POOL_IS_NG() -> bool: view

interface StableSwapNG:
    def N_COINS() -> uint256: view
    def add_liquidity(
        amounts: DynArray[uint256, MAX_COINS],
        min_mint_amount: uint256
    ) -> uint256: nonpayable
    def remove_liquidity(
        amount: uint256,
        min_amounts: DynArray[uint256, MAX_COINS]
    ) -> DynArray[uint256, MAX_COINS]: nonpayable
    def remove_liquidity_one_coin(
        token_amount: uint256,
        i: int128,
        min_amount: uint256
    ) -> uint256: nonpayable
    def remove_liquidity_imbalance(
        amounts: DynArray[uint256, MAX_COINS],
        max_burn_amount: uint256
    ) -> uint256: nonpayable
    def calc_withdraw_one_coin(token_amount: uint256, i: int128) -> uint256: view
    def calc_token_amount(
        amounts: DynArray[uint256, MAX_COINS],
        deposit: bool
    ) -> uint256: view
    def coins(i: uint256) -> address: view
    def fee() -> uint256: view


struct BasePool:
    pool_address: address
    coins: DynArray[address, MAX_COINS]


META_N_COINS: constant(uint256) = 2
MAX_COINS: constant(uint256) = 8
MAX_ALL_COINS: constant(uint256) = MAX_COINS + 1
FEE_DENOMINATOR: constant(uint256) = 10 ** 10
FEE_IMPRECISION: constant(uint256) = 100 * 10 ** 8  # % of the fee

# coin -> pool -> is approved to transfer?
is_approved: HashMap[address, HashMap[address, bool]]
base_pool_coins_spending_approved: HashMap[address, bool]
base_pool_registry: HashMap[address, BasePool]


@internal
@view
def get_coins_from_pool(_pool: address) -> DynArray[address, MAX_COINS]:
    n_coins: uint256 = staticcall StableSwapNG(_pool).N_COINS()
    coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    for i: uint256 in range(n_coins, bound=MAX_COINS):
        coins.append(staticcall StableSwapNG(_pool).coins(i))
    return coins


@internal
def _approve_pool_to_spend_zap_coins(
    pool: address,
    coins: DynArray[address, MAX_COINS],
):
    for i: uint256 in range(len(coins), bound=MAX_COINS):
        extcall IERC20(coins[i]).approve(pool, max_value(uint256))

    self.base_pool_coins_spending_approved[pool] = True


@internal
@view
def _fetch_base_pool_data(_pool: address) -> (address, DynArray[address, MAX_COINS]):

    base_pool: address = staticcall StableSwapMetaNG(_pool).BASE_POOL()
    assert base_pool != empty(address)  # dev: not a metapool
    base_coins: DynArray[address, MAX_COINS] = self.get_coins_from_pool(base_pool)
    return base_pool, base_coins


@internal
def _base_pool_data(_pool: address) -> (address, DynArray[address, MAX_COINS]):

    base_pool_data: BasePool = self.base_pool_registry[_pool]
    if base_pool_data.pool_address == empty(address):

        base_pool: address = empty(address)
        base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
        base_pool, base_coins = self._fetch_base_pool_data(_pool)

        self.base_pool_registry[_pool] = BasePool(
            pool_address=base_pool, coins=base_coins
        )
        return base_pool, base_coins

    return base_pool_data.pool_address, base_pool_data.coins



@view
@external
def calc_token_amount(
    _pool: address,
    _amounts: DynArray[uint256, MAX_ALL_COINS],
    _is_deposit: bool
) -> uint256:
    """
    @notice Calculate addition or reduction in token supply from a deposit or withdrawal
    @dev This calculation accounts for slippage, but not fees.
         Needed to prevent front-running, not for precise calculations!
    @param _pool Address of the pool to deposit into
    @param _amounts Amount of each underlying coin being deposited
    @param _is_deposit set True for deposits, False for withdrawals
    @return Expected amount of LP tokens received
    """
    meta_amounts: uint256[META_N_COINS] = empty(uint256[META_N_COINS])
    base_amounts: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    base_pool: address = empty(address)
    base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    base_pool, base_coins = self._fetch_base_pool_data(_pool)
    base_n_coins: uint256 = len(base_coins)

    meta_amounts[0] = _amounts[0]
    for i: uint256 in range(base_n_coins, bound=MAX_COINS):
        base_amounts.append(_amounts[i + META_N_COINS - 1])

    base_tokens: uint256 = staticcall StableSwapNG(base_pool).calc_token_amount(base_amounts, _is_deposit)
    meta_amounts[META_N_COINS - 1] = base_tokens

    return staticcall StableSwapMetaNG(_pool).calc_token_amount(meta_amounts, _is_deposit)


@external
def add_liquidity(
    _pool: address,
    _deposit_amounts: DynArray[uint256, MAX_ALL_COINS],
    _min_mint_amount: uint256,
    _receiver: address = msg.sender,
) -> uint256:
    """
    @notice Wrap underlying coins and deposit them into `_pool`
    @param _pool Address of the pool to deposit into
    @param _deposit_amounts List of amounts of underlying coins to deposit
    @param _min_mint_amount Minimum amount of LP tokens to mint from the deposit
    @param _receiver Address that receives the LP tokens
    @return Amount of LP tokens received by depositing
    """

    base_amounts: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    deposit_base: bool = False

    # -------------------------- Get base pool data --------------------------

    base_pool: address = empty(address)
    base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    base_pool, base_coins = self._base_pool_data(_pool)
    n_all_coins: uint256 = len(base_coins) + 1

    if not self.base_pool_coins_spending_approved[base_pool]:
        self._approve_pool_to_spend_zap_coins(base_pool, base_coins)

    # ------------------------ Transfer tokens to Zap ------------------------

    meta_amounts: uint256[META_N_COINS] = empty(uint256[META_N_COINS])

    # Transfer meta-token (token in metapool that is not base pool token) if
    # any:
    if _deposit_amounts[0] != 0:
        coin: address = staticcall StableSwapMetaNG(_pool).coins(0)
        if not self.is_approved[coin][_pool]:
            extcall IERC20(coin).approve(_pool, max_value(uint256))
            self.is_approved[coin][_pool] = True
        extcall IERC20(coin).transferFrom(msg.sender, self, _deposit_amounts[0])
        meta_amounts[0] = _deposit_amounts[0]

    # Transfer base pool coins (if any):
    for i: uint256 in range(n_all_coins, bound=MAX_ALL_COINS):

        amount: uint256 = _deposit_amounts[i]
        base_amounts.append(0)
        if i == 0 or amount == 0:
            base_amounts.append(0)
            continue

        deposit_base = True
        base_idx: uint256 = i - 1
        coin: address = base_coins[base_idx]

        extcall IERC20(coin).transferFrom(msg.sender, self, amount)
        base_amounts[base_idx] = amount

    # ----------------------- Deposit to the base pool -----------------------

    if deposit_base:
        meta_amounts[META_N_COINS - 1] = extcall StableSwapNG(base_pool).add_liquidity(base_amounts, 0)
        if not self.is_approved[base_pool][_pool]:
            extcall IERC20(base_pool).approve(_pool, max_value(uint256))
            self.is_approved[base_pool][_pool] = True

    # ----------------------- Deposit to the meta pool -----------------------

    return extcall StableSwapMetaNG(_pool).add_liquidity(
        meta_amounts,
        _min_mint_amount,
        _receiver
    )


@view
@external
def calc_withdraw_one_coin(_pool: address, _token_amount: uint256, i: int128) -> uint256:
    """
    @notice Calculate the amount received when withdrawing and unwrapping a single coin
    @param _pool Address of the pool to deposit into
    @param _token_amount Amount of LP tokens to burn in the withdrawal
    @param i Index value of the underlying coin to withdraw
    @return Amount of coin received
    """
    if i < convert(META_N_COINS, int128) - 1:
        return staticcall StableSwapMetaNG(_pool).calc_withdraw_one_coin(_token_amount, i)
    else:
        base_pool: address = staticcall StableSwapMetaNG(_pool).BASE_POOL()
        assert base_pool != empty(address)  # dev: not a metapool!
        _base_tokens: uint256 = staticcall StableSwapMetaNG(_pool).calc_withdraw_one_coin(_token_amount, convert(META_N_COINS, int128) - 1)
        return staticcall StableSwapNG(base_pool).calc_withdraw_one_coin(
            _base_tokens,
            i - convert(META_N_COINS - 1, int128)
        )


@external
def remove_liquidity(
    _pool: address,
    _burn_amount: uint256,
    _min_amounts: DynArray[uint256, MAX_ALL_COINS],
    _receiver: address = msg.sender
) -> DynArray[uint256, MAX_ALL_COINS]:
    """
    @notice Withdraw and unwrap coins from the pool
    @dev Withdrawal amounts are based on current deposit ratios
    @param _pool Address of the pool to deposit into
    @param _burn_amount Quantity of LP tokens to burn in the withdrawal
    @param _min_amounts Minimum amounts of underlying coins to receive
    @param _receiver Address that receives the LP tokens
    @return List of amounts of underlying coins that were withdrawn
    """
    extcall IERC20(_pool).transferFrom(msg.sender, self, _burn_amount)

    base_pool: address = empty(address)
    base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    base_pool, base_coins = self._base_pool_data(_pool)
    base_n_coins: uint256 = len(base_coins)

    min_amounts_base: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    amounts: DynArray[uint256, MAX_ALL_COINS] = empty(DynArray[uint256, MAX_ALL_COINS])

    # Withdraw from meta
    meta_received: uint256[META_N_COINS] = extcall StableSwapMetaNG(_pool).remove_liquidity(
        _burn_amount,
        [_min_amounts[0], convert(0, uint256)]
    )

    # Withdraw from base
    for i: uint256 in range(base_n_coins, bound=MAX_COINS):
        min_amounts_base.append(_min_amounts[i + META_N_COINS - 1])
    extcall StableSwapNG(base_pool).remove_liquidity(meta_received[1], min_amounts_base)

    # Transfer all coins out
    coin: address = staticcall StableSwapMetaNG(_pool).coins(0)
    extcall IERC20(coin).transfer(_receiver, meta_received[0])
    amounts.append(meta_received[0])

    for i: uint256 in range(base_n_coins + 1, bound=MAX_ALL_COINS):

        if i == 0:
            continue

        coin = base_coins[i-1]
        amounts.append(staticcall IERC20(coin).balanceOf(self))

        extcall IERC20(coin).transfer(_receiver, amounts[i])

    return amounts


@external
def remove_liquidity_one_coin(
    _pool: address,
    _burn_amount: uint256,
    i: int128,
    _min_amount: uint256,
    _receiver: address=msg.sender
) -> uint256:
    """
    @notice Withdraw and unwrap a single coin from the pool
    @param _pool Address of the pool to deposit into
    @param _burn_amount Amount of LP tokens to burn in the withdrawal
    @param i Index value of the coin to withdraw
    @param _min_amount Minimum amount of underlying coin to receive
    @param _receiver Address that receives the LP tokens
    @return Amount of underlying coin received
    """
    extcall IERC20(_pool).transferFrom(msg.sender, self, _burn_amount)

    coin_amount: uint256 = 0
    if i == 0:
        coin_amount = extcall StableSwapMetaNG(_pool).remove_liquidity_one_coin(
            _burn_amount, i, _min_amount, _receiver
        )
    else:
        base_pool: address = empty(address)
        base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
        base_pool, base_coins = self._base_pool_data(_pool)
        base_n_coins: uint256 = len(base_coins)

        coin: address = base_coins[i - convert(META_N_COINS - 1, int128)]
        # Withdraw a base pool coin
        coin_amount = extcall StableSwapMetaNG(_pool).remove_liquidity_one_coin(
            _burn_amount, convert(META_N_COINS - 1, int128), 0, self
        )
        coin_amount = extcall StableSwapNG(base_pool).remove_liquidity_one_coin(
            coin_amount, i - convert(META_N_COINS - 1, int128), _min_amount
        )
        extcall IERC20(coin).transfer(_receiver, coin_amount)

    return coin_amount


@external
def remove_liquidity_imbalance(
    _pool: address,
    _amounts: DynArray[uint256, MAX_ALL_COINS],
    _max_burn_amount: uint256,
    _receiver: address=msg.sender
) -> uint256:
    """
    @notice Withdraw coins from the pool in an imbalanced amount
    @param _pool Address of the pool to deposit into
    @param _amounts List of amounts of underlying coins to withdraw
    @param _max_burn_amount Maximum amount of LP token to burn in the withdrawal
    @param _receiver Address that receives the LP tokens
    @return Actual amount of the LP token burned in the withdrawal
    """

    base_pool: address = empty(address)
    base_coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    base_pool, base_coins = self._base_pool_data(_pool)
    base_n_coins: uint256 = len(base_coins)

    fee: uint256 = staticcall StableSwapNG(base_pool).fee() * base_n_coins // (4 * (base_n_coins - 1))
    fee += fee * FEE_IMPRECISION // FEE_DENOMINATOR  # Overcharge to account for imprecision

    # Transfer the LP token in
    extcall IERC20(_pool).transferFrom(msg.sender, self, _max_burn_amount)

    withdraw_base: bool = False
    amounts_base: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    amounts_meta: uint256[META_N_COINS] = [_amounts[0], 0]

    # determine amounts to withdraw from base pool
    for i: uint256 in range(base_n_coins, bound=MAX_COINS):
        amount: uint256 = _amounts[META_N_COINS - 1 + i]
        if amount != 0:
            amounts_base.append(amount)
            withdraw_base = True
        else:
            amounts_base.append(0)

    # determine amounts to withdraw from metapool
    if withdraw_base:
        amounts_meta[1] = staticcall StableSwapNG(base_pool).calc_token_amount(amounts_base, False)
        amounts_meta[1] += amounts_meta[1] * fee // FEE_DENOMINATOR + 1

    # withdraw from metapool and return the remaining LP tokens
    burn_amount: uint256 = extcall StableSwapMetaNG(_pool).remove_liquidity_imbalance(amounts_meta, _max_burn_amount)
    extcall IERC20(_pool).transfer(msg.sender, _max_burn_amount - burn_amount)

    # withdraw from base pool
    if withdraw_base:
        extcall StableSwapNG(base_pool).remove_liquidity_imbalance(amounts_base, amounts_meta[1])
        coin: address = base_pool
        leftover: uint256 = staticcall IERC20(coin).balanceOf(self)

        if leftover > 0:
            # if some base pool LP tokens remain, re-deposit them for the caller
            if not self.is_approved[coin][_pool]:
                extcall IERC20(coin).approve(_pool, max_value(uint256))
                self.is_approved[coin][_pool] = True
            burn_amount -= extcall StableSwapMetaNG(_pool).add_liquidity([convert(0, uint256), leftover], 0, msg.sender)

        # transfer withdrawn base pool tokens to caller
        for i: uint256 in range(base_n_coins, bound=MAX_COINS):
            extcall IERC20(base_coins[i]).transfer(_receiver, amounts_base[i])

    # transfer withdrawn metapool tokens to caller
    if _amounts[0] > 0:
        coin: address = staticcall StableSwapMetaNG(_pool).coins(0)
        extcall IERC20(coin).transfer(_receiver, _amounts[0])

    return burn_amount
