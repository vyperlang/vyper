# pragma version >=0.4.2

"""
@title CurveTwocryptoSwapFactory
@custom:version 2.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Permissionless 2-coin cryptoswap pool deployer and registry
"""

# ------------------------------- Version ------------------------------------

version: public(constant(String[8])) = "2.0.0"

# --------------------------------- Interfaces -------------------------------

interface TwocryptoPool:
    def balances(i: uint256) -> uint256: view

interface IERC20:
    def decimals() -> uint256: view


event TwocryptoPoolDeployed:
    pool: address
    name: String[64]
    symbol: String[32]
    coins: address[N_COINS]
    math: address
    salt: bytes32
    precisions: uint256[N_COINS]
    packed_A_gamma: uint256
    packed_fee_params: uint256
    packed_rebalancing_params: uint256
    packed_prices: uint256
    deployer: address


event LiquidityGaugeDeployed:
    pool: address
    gauge: address

event UpdateFeeReceiver:
    _old_fee_receiver: address
    _new_fee_receiver: address

event UpdatePoolImplementation:
    _implemention_id: uint256
    _old_pool_implementation: address
    _new_pool_implementation: address

event UpdateGaugeImplementation:
    _old_gauge_implementation: address
    _new_gauge_implementation: address

event UpdateMathImplementation:
    _old_math_implementation: address
    _new_math_implementation: address

event UpdateViewsImplementation:
    _old_views_implementation: address
    _new_views_implementation: address

event TransferOwnership:
    _old_owner: address
    _new_owner: address


struct PoolArray:
    liquidity_gauge: address
    coins: address[N_COINS]
    decimals: uint256[N_COINS]
    implementation: address


N_COINS: constant(uint256) = 2
A_MULTIPLIER: constant(uint256) = 10000

# Limits
MAX_FEE: constant(uint256) = 10 * 10 ** 9

admin: public(address)
future_admin: public(address)

# fee receiver for all pools:
fee_receiver: public(address)

pool_implementations: public(HashMap[uint256, address])
gauge_implementation: public(address)
views_implementation: public(address)
math_implementation: public(address)

# mapping of coins -> pools for trading
# a mapping key is generated for each pair of addresses via
# `bitwise_xor(convert(a, uint256), convert(b, uint256))`
markets: HashMap[uint256, DynArray[address, 4294967296]]
pool_data: HashMap[address, PoolArray]
pool_list: public(DynArray[address, 4294967296])   # master list of pools

deployer: immutable(address)


@deploy
def __init__(_fee_receiver: address):
    deployer = msg.sender
    self.admin = msg.sender
    self.fee_receiver = _fee_receiver


@external
def set_owner(_owner: address):
    
    assert msg.sender == deployer
    assert self.admin == deployer
    assert _owner != deployer

    self.admin = _owner


@internal
@pure
def _pack_3(x: uint256[3]) -> uint256:
    """
    @notice Packs 3 integers with values <= 10**18 into a uint256
    @param x The uint256[3] to pack
    @return The packed uint256
    """
    return (x[0] << 128) | (x[1] << 64) | x[2]


@pure
@internal
def _pack_2(p1: uint256, p2: uint256) -> uint256:
    return p1 | (p2 << 128)


# <--- Pool Deployers --->

@external
def deploy_pool(
    _name: String[64],
    _symbol: String[32],
    _coins: address[N_COINS],
    implementation_id: uint256,
    A: uint256,
    gamma: uint256,
    mid_fee: uint256,
    out_fee: uint256,
    fee_gamma: uint256,
    allowed_extra_profit: uint256,
    adjustment_step: uint256,
    ma_exp_time: uint256,
    initial_price: uint256,
) -> address:
    """
    @notice Deploy a new pool
    @param _name Name of the new plain pool
    @param _symbol Symbol for the new plain pool - will be concatenated with factory symbol

    @return Address of the deployed pool
    """
    pool_implementation: address = self.pool_implementations[implementation_id]
    _math_implementation: address = self.math_implementation
    assert pool_implementation != empty(address), "Pool implementation not set"
    assert _math_implementation != empty(address), "Math implementation not set"

    assert mid_fee < MAX_FEE-1  # mid_fee can be zero
    assert out_fee >= mid_fee
    assert out_fee < MAX_FEE-1
    assert fee_gamma < 10**18+1
    assert fee_gamma > 0

    assert allowed_extra_profit < 10**18+1

    assert adjustment_step < 10**18+1
    assert adjustment_step > 0

    assert ma_exp_time < 872542  # 7 * 24 * 60 * 60 // ln(2)
    assert ma_exp_time > 86  # 60 // ln(2)

    assert initial_price > 10**6 and initial_price < 10**30  # dev: initial price out of bound

    assert _coins[0] != _coins[1], "Duplicate coins"

    decimals: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    for i: uint256 in range(N_COINS):
        d: uint256 = staticcall IERC20(_coins[i]).decimals()
        assert d < 19, "Max 18 decimals for coins"
        decimals[i] = d
        precisions[i] = 10 ** (18 - d)

    # pack precision
    packed_precisions: uint256 = self._pack_2(precisions[0], precisions[1])

    # pack fees
    packed_fee_params: uint256 = self._pack_3(
        [mid_fee, out_fee, fee_gamma]
    )

    # pack liquidity rebalancing params
    packed_rebalancing_params: uint256 = self._pack_3(
        [allowed_extra_profit, adjustment_step, ma_exp_time]
    )

    # pack gamma and A
    packed_gamma_A: uint256 = self._pack_2(gamma, A)

    # pool is an IERC20 implementation
    _salt: bytes32 = block.prevhash
    pool: address = create_from_blueprint(
        pool_implementation,  # blueprint: address
        _name,  # String[64]
        _symbol,  # String[32]
        _coins,  # address[N_COINS]
        _math_implementation,  # address
        _salt,  # bytes32
        packed_precisions,  # uint256
        packed_gamma_A,  # uint256
        packed_fee_params,  # uint256
        packed_rebalancing_params,  # uint256
        initial_price,  # uint256
        code_offset=3,
    )

    # populate pool data
    self.pool_list.append(pool)

    self.pool_data[pool].decimals = decimals
    self.pool_data[pool].coins = _coins
    self.pool_data[pool].implementation = pool_implementation

    # add coins to market:
    self._add_coins_to_market(_coins[0], _coins[1], pool)

    log TwocryptoPoolDeployed(
        pool=pool,
        name=_name,
        symbol=_symbol,
        coins=_coins,
        math=_math_implementation,
        salt=_salt,
        precisions=precisions,
        packed_A_gamma=packed_gamma_A,
        packed_fee_params=packed_fee_params,
        packed_rebalancing_params=packed_rebalancing_params,
        packed_prices=initial_price,
        deployer=msg.sender,
    )

    return pool


@internal
def _add_coins_to_market(coin_a: address, coin_b: address, pool: address):

    key: uint256 = (
        convert(coin_a, uint256) ^ convert(coin_b, uint256)
    )
    self.markets[key].append(pool)


@external
def deploy_gauge(_pool: address) -> address:
    """
    @notice Deploy a liquidity gauge for a factory pool
    @param _pool Factory pool address to deploy a gauge for
    @return Address of the deployed gauge
    """
    assert self.pool_data[_pool].coins[0] != empty(address), "Unknown pool"
    assert self.pool_data[_pool].liquidity_gauge == empty(address), "Gauge already deployed"
    assert self.gauge_implementation != empty(address), "Gauge implementation not set"

    gauge: address = create_from_blueprint(self.gauge_implementation, _pool, code_offset=3)
    self.pool_data[_pool].liquidity_gauge = gauge

    log LiquidityGaugeDeployed(pool=_pool, gauge=gauge)
    return gauge


# <--- Admin // Guarded Functionality --->


@external
def set_fee_receiver(_fee_receiver: address):
    """
    @notice Set fee receiver
    @param _fee_receiver Address that fees are sent to
    """
    assert msg.sender == self.admin, "dev: admin only"

    log UpdateFeeReceiver(_old_fee_receiver=self.fee_receiver, _new_fee_receiver=_fee_receiver)
    self.fee_receiver = _fee_receiver


@external
def set_pool_implementation(
    _pool_implementation: address, _implementation_index: uint256
):
    """
    @notice Set pool implementation
    @dev Set to empty(address) to prevent deployment of new pools
    @param _pool_implementation Address of the new pool implementation
    @param _implementation_index Index of the pool implementation
    """
    assert msg.sender == self.admin, "dev: admin only"

    log UpdatePoolImplementation(
        _implemention_id=_implementation_index,
        _old_pool_implementation=self.pool_implementations[_implementation_index],
        _new_pool_implementation=_pool_implementation
    )

    self.pool_implementations[_implementation_index] = _pool_implementation


@external
def set_gauge_implementation(_gauge_implementation: address):
    """
    @notice Set gauge implementation
    @dev Set to empty(address) to prevent deployment of new gauges
    @param _gauge_implementation Address of the new token implementation
    """
    assert msg.sender == self.admin, "dev: admin only"

    log UpdateGaugeImplementation(_old_gauge_implementation=self.gauge_implementation, _new_gauge_implementation=_gauge_implementation)
    self.gauge_implementation = _gauge_implementation


@external
def set_views_implementation(_views_implementation: address):
    """
    @notice Set views contract implementation
    @param _views_implementation Address of the new views contract
    """
    assert msg.sender == self.admin,  "dev: admin only"

    log UpdateViewsImplementation(_old_views_implementation=self.views_implementation, _new_views_implementation=_views_implementation)
    self.views_implementation = _views_implementation


@external
def set_math_implementation(_math_implementation: address):
    """
    @notice Set math implementation
    @param _math_implementation Address of the new math contract
    """
    assert msg.sender == self.admin, "dev: admin only"

    log UpdateMathImplementation(_old_math_implementation=self.math_implementation, _new_math_implementation=_math_implementation)
    self.math_implementation = _math_implementation


@external
def commit_transfer_ownership(_addr: address):
    """
    @notice Transfer ownership of this contract to `addr`
    @param _addr Address of the new owner
    """
    assert msg.sender == self.admin, "dev: admin only"

    self.future_admin = _addr


@external
def accept_transfer_ownership():
    """
    @notice Accept a pending ownership transfer
    @dev Only callable by the new owner
    """
    assert msg.sender == self.future_admin, "dev: future admin only"

    log TransferOwnership(_old_owner=self.admin, _new_owner=msg.sender)
    self.admin = msg.sender


# <--- Factory Getters --->


@view
@external
def find_pool_for_coins(_from: address, _to: address, i: uint256 = 0) -> address:
    """
    @notice Find an available pool for exchanging two coins
    @param _from Address of coin to be sent
    @param _to Address of coin to be received
    @param i Index value. When multiple pools are available
            this value is used to return the n'th address.
    @return Pool address
    """
    key: uint256 = convert(_from, uint256) ^ convert(_to, uint256)
    return self.markets[key][i]


# <--- Pool Getters --->


@view
@external
def pool_count() -> uint256:
    """
    @notice Get number of pools deployed from the factory
    @return Number of pools deployed from factory
    """
    return len(self.pool_list)


@view
@external
def get_coins(_pool: address) -> address[N_COINS]:
    """
    @notice Get the coins within a pool
    @param _pool Pool address
    @return List of coin addresses
    """
    return self.pool_data[_pool].coins


@view
@external
def get_decimals(_pool: address) -> uint256[N_COINS]:
    """
    @notice Get decimal places for each coin within a pool
    @param _pool Pool address
    @return uint256 list of decimals
    """
    return self.pool_data[_pool].decimals


@view
@external
def get_balances(_pool: address) -> uint256[N_COINS]:
    """
    @notice Get balances for each coin within a pool
    @dev For pools using lending, these are the wrapped coin balances
    @param _pool Pool address
    @return uint256 list of balances
    """
    return [staticcall TwocryptoPool(_pool).balances(0), staticcall TwocryptoPool(_pool).balances(1)]


@view
@external
def get_coin_indices(
    _pool: address,
    _from: address,
    _to: address
) -> (uint256, uint256):
    """
    @notice Convert coin addresses to indices for use with pool methods
    @param _pool Pool address
    @param _from Coin address to be used as `i` within a pool
    @param _to Coin address to be used as `j` within a pool
    @return uint256 `i`, uint256 `j`
    """
    coins: address[2] = self.pool_data[_pool].coins

    if _from == coins[0] and _to == coins[1]:
        return 0, 1
    elif _from == coins[1] and _to == coins[0]:
        return 1, 0
    else:
        raise "Coins not found"


@view
@external
def get_gauge(_pool: address) -> address:
    """
    @notice Get the address of the liquidity gauge contract for a factory pool
    @dev Returns `empty(address)` if a gauge has not been deployed
    @param _pool Pool address
    @return Implementation contract address
    """
    return self.pool_data[_pool].liquidity_gauge


@view
@external
def get_market_counts(coin_a: address, coin_b: address) -> uint256:
    """
    @notice Gets the number of markets with the specified coins.
    @return Number of pools with the input coins
    """

    key: uint256 = (
        convert(coin_a, uint256) ^ convert(coin_b, uint256)
    )

    return len(self.markets[key])
