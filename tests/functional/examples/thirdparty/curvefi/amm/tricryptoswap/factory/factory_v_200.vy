# pragma version >=0.4.2
# pragma optimize gas
# pragma evm-version paris

"""
@title CurveTricryptoSwapFactory
@custom:version 2.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Permissionless 3-coin cryptoswap pool deployer and registry
"""

# ------------------------------- Version ------------------------------------

version: public(constant(String[8])) = "2.0.0"

# ------------------------------- Interfaces ---------------------------------

interface TricryptoPool:
    def balances(i: uint256) -> uint256: view

interface IERC20:
    def decimals() -> uint256: view


event TricryptoPoolDeployed:
    pool: address
    name: String[64]
    symbol: String[32]
    weth: address
    coins: address[N_COINS]
    math: address
    salt: bytes32
    packed_precisions: uint256
    packed_A_gamma: uint256
    packed_fee_params: uint256
    packed_rebalancing_params: uint256
    packed_prices: uint256
    deployer: address

event UpdateFeeReceiver:
    _old_fee_receiver: address
    _new_fee_receiver: address

event UpdatePoolImplementation:
    _implemention_id: uint256
    _old_pool_implementation: address
    _new_pool_implementation: address

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
    coins: address[N_COINS]
    decimals: uint256[N_COINS]
    implementation: address


N_COINS: constant(uint256) = 3
A_MULTIPLIER: constant(uint256) = 10000

# Limits
MAX_FEE: constant(uint256) = 10 * 10 ** 9

MIN_GAMMA: constant(uint256) = 10 ** 10
MAX_GAMMA: constant(uint256) = 5 * 10**16

MIN_A: constant(uint256) = N_COINS ** N_COINS * A_MULTIPLIER // 100
MAX_A: constant(uint256) = 1000 * A_MULTIPLIER * N_COINS**N_COINS

PRICE_SIZE: constant(uint128) = 128  # 256 // (N_COINS - 1) where N_COINS = 3
PRICE_MASK: constant(uint256) = 340282366920938463463374607431768211455  # 2**128 - 1

admin: public(address)
future_admin: public(address)

# fee receiver for all pools:
fee_receiver: public(address)

pool_implementations: public(HashMap[uint256, address])
views_implementation: public(address)
math_implementation: public(address)

# mapping of coins -> pools for trading
# a mapping key is generated for each pair of addresses via
# `bitwise_xor(convert(a, uint256), convert(b, uint256))`
markets: HashMap[uint256, address[4294967296]]
market_counts: HashMap[uint256, uint256]

pool_count: public(uint256)              # actual length of pool_list
pool_data: HashMap[address, PoolArray]
pool_list: public(address[4294967296])   # master list of pools

deployer: immutable(address)


@deploy
def __init__(_fee_receiver: address):

    self.fee_receiver = _fee_receiver
    self.admin = msg.sender
    deployer = msg.sender

    log UpdateFeeReceiver(_old_fee_receiver=empty(address), _new_fee_receiver=_fee_receiver)
    log TransferOwnership(_old_owner=empty(address), _new_owner=msg.sender)


@external
def set_owner(_owner: address):
    
    assert msg.sender == deployer
    assert self.admin == deployer
    assert _owner != deployer

    self.admin = _owner
    log TransferOwnership(_old_owner=deployer, _new_owner=_owner)


@internal
@view
def _pack(x: uint256[3]) -> uint256:
    """
    @notice Packs 3 integers with values <= 10**18 into a uint256
    @param x The uint256[3] to pack
    @return The packed uint256
    """
    return (x[0] << 128) | (x[1] << 64) | x[2]



# <--- Pool Deployers --->

@external
def deploy_pool(
    _name: String[64],
    _symbol: String[32],
    _coins: address[N_COINS],
    _weth: address,
    implementation_id: uint256,
    A: uint256,
    gamma: uint256,
    mid_fee: uint256,
    out_fee: uint256,
    fee_gamma: uint256,
    allowed_extra_profit: uint256,
    adjustment_step: uint256,
    ma_exp_time: uint256,
    initial_prices: uint256[N_COINS-1],
) -> address:
    """
    @notice Deploy a new pool
    @param _name Name of the new plain pool
    @param _symbol Symbol for the new plain pool - will be concatenated with factory symbol

    @return Address of the deployed pool
    """
    pool_implementation: address = self.pool_implementations[implementation_id]
    assert pool_implementation != empty(address), "Pool implementation not set"

    # Validate parameters
    assert A > MIN_A-1
    assert A < MAX_A+1

    assert gamma > MIN_GAMMA-1
    assert gamma < MAX_GAMMA+1

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

    assert min(initial_prices[0], initial_prices[1]) > 10**6
    assert max(initial_prices[0], initial_prices[1]) < 10**30

    assert _coins[0] != _coins[1] and _coins[1] != _coins[2] and _coins[0] != _coins[2], "Duplicate coins"

    decimals: uint256[N_COINS] = empty(uint256[N_COINS])
    precisions: uint256[N_COINS] = empty(uint256[N_COINS])
    for i: uint256 in range(N_COINS):
        d: uint256 = staticcall IERC20(_coins[i]).decimals()
        assert d < 19, "Max 18 decimals for coins"
        decimals[i] = d
        precisions[i] = 10** (18 - d)

    # pack precisions
    packed_precisions: uint256 = self._pack(precisions)

    # pack fees
    packed_fee_params: uint256 = self._pack(
        [mid_fee, out_fee, fee_gamma]
    )

    # pack liquidity rebalancing params
    packed_rebalancing_params: uint256 = self._pack(
        [allowed_extra_profit, adjustment_step, ma_exp_time]
    )

    # pack A_gamma
    packed_A_gamma: uint256 = A << 128
    packed_A_gamma = packed_A_gamma | gamma

    # pack initial prices
    packed_prices: uint256 = 0
    for k: uint256 in range(N_COINS - 1):
        packed_prices = packed_prices << PRICE_SIZE
        p: uint256 = initial_prices[N_COINS - 2 - k]
        assert p < PRICE_MASK
        packed_prices = p | packed_prices

    # pool is an IERC20 implementation
    _salt: bytes32 = block.prevhash
    _math_implementation: address = self.math_implementation
    pool: address = create_from_blueprint(
        pool_implementation,
        _name,
        _symbol,
        _coins,
        _math_implementation,
        _weth,
        _salt,
        packed_precisions,
        packed_A_gamma,
        packed_fee_params,
        packed_rebalancing_params,
        packed_prices,
        code_offset=3
    )

    # populate pool data
    length: uint256 = self.pool_count
    self.pool_list[length] = pool
    self.pool_count = length + 1
    self.pool_data[pool].decimals = decimals
    self.pool_data[pool].coins = _coins
    self.pool_data[pool].implementation = pool_implementation

    # add coins to market:
    self._add_coins_to_market(_coins[0], _coins[1], pool)
    self._add_coins_to_market(_coins[0], _coins[2], pool)
    self._add_coins_to_market(_coins[1], _coins[2], pool)

    log TricryptoPoolDeployed(
        pool=pool,
        name=_name,
        symbol=_symbol,
        weth=_weth,
        coins=_coins,
        math=_math_implementation,
        salt=_salt,
        packed_precisions=packed_precisions,
        packed_A_gamma=packed_A_gamma,
        packed_fee_params=packed_fee_params,
        packed_rebalancing_params=packed_rebalancing_params,
        packed_prices=packed_prices,
        deployer=msg.sender,
    )

    return pool


@internal
def _add_coins_to_market(coin_a: address, coin_b: address, pool: address):

    key: uint256 = (
        convert(coin_a, uint256) ^ convert(coin_b, uint256)
    )

    length: uint256 = self.market_counts[key]
    self.markets[key][length] = pool
    self.market_counts[key] = length + 1


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
def get_implementation_address(_pool: address) -> address:
    """
    @notice Get the address of the implementation contract used for a factory pool
    @param _pool Pool address
    @return Implementation contract address
    """
    return self.pool_data[_pool].implementation


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
    return [
        staticcall TricryptoPool(_pool).balances(0),
        staticcall TricryptoPool(_pool).balances(1),
        staticcall TricryptoPool(_pool).balances(2),
    ]


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
    coins: address[N_COINS] = self.pool_data[_pool].coins

    for i: uint256 in range(N_COINS):
        for j: uint256 in range(N_COINS):
            if i == j:
                continue

            if coins[i] == _from and coins[j] == _to:
                return i, j

    raise "Coins not found"


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

    return self.market_counts[key]
