# pragma version >=0.4.2
# pragma evm-version shanghai

"""
@title CurveStableSwapFactory
@custom:version 1.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2023-2024 - all rights reserved
@notice Permissionless pool deployer and registry
"""
# ------------------------------- Version ---------------------------------

version: public(constant(String[8])) = "1.0.0"

# ------------------------------- Interfaces ---------------------------------

struct PoolArray:
    base_pool: address
    implementation: address
    liquidity_gauge: address
    coins: DynArray[address, MAX_COINS]
    decimals: DynArray[uint256, MAX_COINS]
    n_coins: uint256
    asset_types: DynArray[uint8, MAX_COINS]

struct BasePoolArray:
    lp_token: address
    coins: DynArray[address, MAX_COINS]
    decimals: uint256
    n_coins: uint256
    asset_types: DynArray[uint8, MAX_COINS]


interface AddressProvider:
    def admin() -> address: view

interface IERC20:
    def balanceOf(_addr: address) -> uint256: view
    def decimals() -> uint256: view
    def totalSupply() -> uint256: view

interface CurvePool:
    def A() -> uint256: view
    def fee() -> uint256: view
    def admin_fee() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def admin_balances(i: uint256) -> uint256: view
    def get_virtual_price() -> uint256: view
    def coins(i: uint256) -> address: view

interface CurveFactoryMetapool:
    def coins(i :uint256) -> address: view
    def decimals() -> uint256: view


event BasePoolAdded:
    base_pool: address

event PlainPoolDeployed:
    pool: address
    coins: DynArray[address, MAX_COINS]
    A: uint256
    fee: uint256
    deployer: address

event MetaPoolDeployed:
    pool: address
    coin: address
    base_pool: address
    A: uint256
    fee: uint256
    deployer: address

event LiquidityGaugeDeployed:
    pool: address
    gauge: address

MAX_COINS: constant(uint256) = 8

MAX_FEE: constant(uint256) = 5 * 10 ** 9
FEE_DENOMINATOR: constant(uint256) = 10 ** 10

admin: public(address)
future_admin: public(address)

asset_types: public(HashMap[uint8, String[20]])

pool_list: public(address[4294967296])   # master list of pools
pool_count: public(uint256)              # actual length of pool_list
pool_data: HashMap[address, PoolArray]

base_pool_list: public(address[4294967296])   # list of base pools
base_pool_count: public(uint256)              # number of base pools
base_pool_data: public(HashMap[address, BasePoolArray])

# asset -> is used in a metapool?
base_pool_assets: public(HashMap[address, bool])

# index -> implementation address
pool_implementations: public(HashMap[uint256, address])
metapool_implementations: public(HashMap[uint256, address])
math_implementation: public(address)
gauge_implementation: public(address)
views_implementation: public(address)

# fee receiver for all pools
fee_receiver: public(address)

# mapping of coins -> pools for trading
# a mapping key is generated for each pair of addresses via
# `bitwise_xor(convert(a, uint256), convert(b, uint256))`
markets: HashMap[uint256, address[4294967296]]
market_counts: HashMap[uint256, uint256]

deployer: immutable(address)

@deploy
def __init__(_fee_receiver: address, _owner: address):

    self.fee_receiver = _fee_receiver
    self.admin = msg.sender
    deployer = msg.sender

    self.asset_types[0] = "Standard"
    self.asset_types[1] = "Oracle"
    self.asset_types[2] = "Rebasing"
    self.asset_types[3] = "IERC4626"


@external
def set_owner(_owner: address):
    
    assert msg.sender == deployer
    assert self.admin == deployer
    assert _owner != deployer

    self.admin = _owner


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
    key: uint256 = (convert(_from, uint256) ^ convert(_to, uint256))
    return self.markets[key][i]


# <--- Pool Getters --->

@view
@external
def get_base_pool(_pool: address) -> address:
    """
    @notice Get the base pool for a given factory metapool
    @param _pool Metapool address
    @return Address of base pool
    """
    return self.pool_data[_pool].base_pool


@view
@external
def get_n_coins(_pool: address) -> (uint256):
    """
    @notice Get the number of coins in a pool
    @param _pool Pool address
    @return Number of coins
    """
    return self.pool_data[_pool].n_coins


@view
@external
def get_meta_n_coins(_pool: address) -> (uint256, uint256):
    """
    @notice Get the number of coins in a metapool
    @param _pool Pool address
    @return Number of wrapped coins, number of underlying coins
    """
    base_pool: address = self.pool_data[_pool].base_pool
    return 2, self.base_pool_data[base_pool].n_coins + 1


@view
@external
def get_coins(_pool: address) -> DynArray[address, MAX_COINS]:
    """
    @notice Get the coins within a pool
    @param _pool Pool address
    @return List of coin addresses
    """
    return self.pool_data[_pool].coins


@view
@external
def get_underlying_coins(_pool: address) -> DynArray[address, MAX_COINS]:
    """
    @notice Get the underlying coins within a pool
    @dev Reverts if a pool does not exist or is not a metapool
    @param _pool Pool address
    @return List of coin addresses
    """
    coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    base_pool: address = self.pool_data[_pool].base_pool
    assert base_pool != empty(address)  # dev: pool is not metapool

    coins.append(self.pool_data[_pool].coins[0])
    base_pool_n_coins: uint256 = len(self.base_pool_data[base_pool].coins)
    for i: uint256 in range(1, MAX_COINS):
        if i - 1 == base_pool_n_coins:
            break

        coins.append(self.base_pool_data[base_pool].coins[i - 1])

    return coins


@view
@external
def get_decimals(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get decimal places for each coin within a pool
    @param _pool Pool address
    @return uint256 list of decimals
    """
    return self.pool_data[_pool].decimals


@view
@external
def get_underlying_decimals(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get decimal places for each underlying coin within a pool
    @param _pool Pool address
    @return uint256 list of decimals
    """
    # decimals are tightly packed as a series of uint8 within a little-endian bytes32
    # the packed value is stored as uint256 to simplify unpacking via shift and modulo
    pool_decimals: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    pool_decimals = self.pool_data[_pool].decimals
    decimals: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    decimals.append(pool_decimals[0])
    base_pool: address = self.pool_data[_pool].base_pool
    packed_decimals: uint256 = self.base_pool_data[base_pool].decimals

    for i: uint256 in range(MAX_COINS):
        unpacked: uint256 = (packed_decimals >> 8 * i) % 256
        if unpacked == 0:
            break

        decimals.append(unpacked)

    return decimals


@view
@external
def get_metapool_rates(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get rates for coins within a metapool
    @param _pool Pool address
    @return Rates for each coin, precision normalized to 10**18
    """
    rates: DynArray[uint256, MAX_COINS] = [10**18, 0]
    rates[1] = staticcall (CurvePool(self.pool_data[_pool].base_pool)).get_virtual_price()
    return rates


@view
@external
def get_balances(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get balances for each coin within a pool
    @dev For pools using lending, these are the wrapped coin balances
    @param _pool Pool address
    @return uint256 list of balances
    """
    balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    if self.pool_data[_pool].base_pool != empty(address):
        balances.append(staticcall CurvePool(_pool).balances(0))
        balances.append(staticcall CurvePool(_pool).balances(1))
        return balances

    n_coins: uint256 = self.pool_data[_pool].n_coins
    for i: uint256 in range(MAX_COINS):

        if i == n_coins:
            break

        balances.append(staticcall CurvePool(_pool).balances(i))


    return balances


@view
@external
def get_underlying_balances(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get balances for each underlying coin within a metapool
    @param _pool Metapool address
    @return uint256 list of underlying balances
    """

    base_pool: address = self.pool_data[_pool].base_pool
    assert base_pool != empty(address)  # dev: pool is not a metapool

    underlying_balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    underlying_balances[0] = staticcall CurvePool(_pool).balances(0)

    base_total_supply: uint256 = staticcall IERC20(self.pool_data[_pool].coins[1]).totalSupply()
    if base_total_supply > 0:
        underlying_pct: uint256 = staticcall CurvePool(_pool).balances(1) * 10**36 // base_total_supply
        n_coins: uint256 = self.base_pool_data[base_pool].n_coins
        for i: uint256 in range(MAX_COINS):
            if i == n_coins:
                break
            underlying_balances[i + 1] = staticcall CurvePool(base_pool).balances(i) * underlying_pct // 10**36

    return underlying_balances


@view
@external
def get_A(_pool: address) -> uint256:
    """
    @notice Get the amplfication co-efficient for a pool
    @param _pool Pool address
    @return uint256 A
    """
    return staticcall CurvePool(_pool).A()


@view
@external
def get_fees(_pool: address) -> (uint256, uint256):
    """
    @notice Get the fees for a pool
    @dev Fees are expressed as integers
    @return Pool fee and admin fee as uint256 with 1e10 precision
    """
    return staticcall CurvePool(_pool).fee(), staticcall CurvePool(_pool).admin_fee()


@view
@external
def get_admin_balances(_pool: address) -> DynArray[uint256, MAX_COINS]:
    """
    @notice Get the current admin balances (uncollected fees) for a pool
    @param _pool Pool address
    @return List of uint256 admin balances
    """
    n_coins: uint256 = self.pool_data[_pool].n_coins
    admin_balances: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    for i: uint256 in range(MAX_COINS):
        if i == n_coins:
            break
        admin_balances.append(staticcall CurvePool(_pool).admin_balances(i))
    return admin_balances


@view
@external
def get_coin_indices(
    _pool: address,
    _from: address,
    _to: address
) -> (int128, int128, bool):
    """
    @notice Convert coin addresses to indices for use with pool methods
    @param _pool Pool address
    @param _from Coin address to be used as `i` within a pool
    @param _to Coin address to be used as `j` within a pool
    @return int128 `i`, int128 `j`, boolean indicating if `i` and `j` are underlying coins
    """
    coin: address = self.pool_data[_pool].coins[0]
    base_pool: address = self.pool_data[_pool].base_pool
    if coin in [_from, _to] and base_pool != empty(address):
        base_lp_token: address = self.pool_data[_pool].coins[1]
        if base_lp_token in [_from, _to]:
            # True and False convert to 1 and 0 - a bit of voodoo that
            # works because we only ever have 2 non-underlying coins if base pool is empty(address)
            return convert(_to == coin, int128), convert(_from == coin, int128), False

    found_market: bool = False
    i: uint256 = 0
    j: uint256 = 0
    for x: uint256 in range(MAX_COINS):
        if base_pool == empty(address):
            if x >= MAX_COINS:
                raise "No available market"
            if x != 0:
                coin = self.pool_data[_pool].coins[x]
        else:
            if x != 0:
                coin = self.base_pool_data[base_pool].coins[x-1]
        if coin == empty(address):
            raise "No available market"
        if coin == _from:
            i = x
        elif coin == _to:
            j = x
        else:
            continue
        if found_market:
            # the second time we find a match, break out of the loop
            break
        # the first time we find a match, set `found_market` to True
        found_market = True

    return convert(i, int128), convert(j, int128), True


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
def get_implementation_address(_pool: address) -> address:
    """
    @notice Get the address of the implementation contract used for a factory pool
    @param _pool Pool address
    @return Implementation contract address
    """
    return self.pool_data[_pool].implementation


@view
@external
def is_meta(_pool: address) -> bool:
    """
    @notice Verify `_pool` is a metapool
    @param _pool Pool address
    @return True if `_pool` is a metapool
    """
    return self.pool_data[_pool].base_pool != empty(address)


@view
@external
def get_pool_asset_types(_pool: address) -> DynArray[uint8, MAX_COINS]:
    """
    @notice Query the asset type of `_pool`
    @param _pool Pool Address
    @return Dynarray of uint8 indicating the pool asset type
            Asset Types:
                0. Standard IERC20 token with no additional features
                1. Oracle - token with rate oracle (e.g. wrapped staked ETH)
                2. Rebasing - token with rebase (e.g. staked ETH)
                3. IERC4626 - e.g. sDAI
    """
    return self.pool_data[_pool].asset_types


# <--- Pool Deployers --->

@external
def deploy_plain_pool(
    _name: String[32],
    _symbol: String[10],
    _coins: DynArray[address, MAX_COINS],
    _A: uint256,
    _fee: uint256,
    _offpeg_fee_multiplier: uint256,
    _ma_exp_time: uint256,
    _implementation_idx: uint256,
    _asset_types: DynArray[uint8, MAX_COINS],
    _method_ids: DynArray[bytes4, MAX_COINS],
    _oracles: DynArray[address, MAX_COINS],
) -> address:
    """
    @notice Deploy a new plain pool
    @param _name Name of the new plain pool
    @param _symbol Symbol for the new plain pool - will be
                   concatenated with factory symbol
    @param _coins List of addresses of the coins being used in the pool.
    @param _A Amplification co-efficient - a lower value here means
              less tolerance for imbalance within the pool's assets.
              Suggested values include:
               * Uncollateralized algorithmic stablecoins: 5-10
               * Non-redeemable, collateralized assets: 100
               * Redeemable assets: 200-400
    @param _fee Trade fee, given as an integer with 1e10 precision. The
                maximum is 1% (100000000). 50% of the fee is distributed to veCRV holders.
    @param _ma_exp_time Averaging window of oracle. Set as time_in_seconds // ln(2)
                        Example: for 10 minute EMA, _ma_exp_time is 600 // ln(2) ~= 866
    @param _implementation_idx Index of the implementation to use
    @param _asset_types Asset types for pool, as an integer
    @param _method_ids Array of first four bytes of the Keccak-256 hash of the function signatures
                       of the oracle addresses that gives rate oracles.
                       Calculated as: keccak(text=event_signature.replace(" ", ""))[:4]
    @param _oracles Array of rate oracle addresses.
    @return Address of the deployed pool
    """
    assert len(_coins) >= 2  # dev: pool needs to have at least two coins!
    assert len(_coins) == len(_method_ids)  # dev: All coin arrays should be same length
    assert len(_coins) ==  len(_oracles)  # dev: All coin arrays should be same length
    assert len(_coins) ==  len(_asset_types)  # dev: All coin arrays should be same length
    assert _fee <= 100000000, "Invalid fee"
    assert _offpeg_fee_multiplier * _fee <= MAX_FEE * FEE_DENOMINATOR

    n_coins: uint256 = len(_coins)
    _rate_multipliers: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])
    decimals: DynArray[uint256, MAX_COINS] = empty(DynArray[uint256, MAX_COINS])

    for i: uint256 in range(MAX_COINS):
        if i == n_coins:
            break

        coin: address = _coins[i]

        decimals.append(staticcall IERC20(coin).decimals())
        assert decimals[i] < 19, "Max 18 decimals for coins"

        _rate_multipliers.append(10 ** (36 - decimals[i]))

        for j: uint256 in range(i, i + MAX_COINS, bound=MAX_COINS):
            if (j + 1) == n_coins:
                break
            assert coin != _coins[j+1], "Duplicate coins"

    implementation: address = self.pool_implementations[_implementation_idx]
    assert implementation != empty(address), "Invalid implementation index"

    pool: address = create_from_blueprint(
        implementation,
        _name,                                          # _name: String[32]
        _symbol,                                        # _symbol: String[10]
        _A,                                             # _A: uint256
        _fee,                                           # _fee: uint256
        _offpeg_fee_multiplier,                         # _offpeg_fee_multiplier: uint256
        _ma_exp_time,                                   # _ma_exp_time: uint256
        _coins,                                         # _coins: DynArray[address, MAX_COINS]
        _rate_multipliers,                              # _rate_multipliers: DynArray[uint256, MAX_COINS]
        _asset_types,                                   # _asset_types: DynArray[uint8, MAX_COINS]
        _method_ids,                                    # _method_ids: DynArray[bytes4, MAX_COINS]
        _oracles,                                       # _oracles: DynArray[address, MAX_COINS]
        code_offset=3
    )

    length: uint256 = self.pool_count
    self.pool_list[length] = pool
    self.pool_count = length + 1
    self.pool_data[pool].decimals = decimals
    self.pool_data[pool].n_coins = n_coins
    self.pool_data[pool].base_pool = empty(address)
    self.pool_data[pool].implementation = implementation
    self.pool_data[pool].asset_types = _asset_types

    for i: uint256 in range(MAX_COINS):
        if i == n_coins:
            break

        coin: address = _coins[i]
        self.pool_data[pool].coins.append(coin)

        for j: uint256 in range(i, i + MAX_COINS, bound=MAX_COINS):
            if (j + 1) == n_coins:
                break
            swappable_coin: address = _coins[j + 1]
            key: uint256 = (convert(coin, uint256) ^ convert(swappable_coin, uint256))
            length = self.market_counts[key]
            self.markets[key][length] = pool
            self.market_counts[key] = length + 1

    log PlainPoolDeployed(pool=pool, coins=_coins, A=_A, fee=_fee, deployer=msg.sender)
    return pool


@external
def deploy_metapool(
    _base_pool: address,
    _name: String[32],
    _symbol: String[10],
    _coin: address,
    _A: uint256,
    _fee: uint256,
    _offpeg_fee_multiplier: uint256,
    _ma_exp_time: uint256,
    _implementation_idx: uint256,
    _asset_type: uint8,
    _method_id: bytes4,
    _oracle: address,
) -> address:
    """
    @notice Deploy a new metapool
    @param _base_pool Address of the base pool to use
                      within the metapool
    @param _name Name of the new metapool
    @param _symbol Symbol for the new metapool - will be
                   concatenated with the base pool symbol
    @param _coin Address of the coin being used in the metapool
    @param _A Amplification co-efficient - a higher value here means
              less tolerance for imbalance within the pool's assets.
              Suggested values include:
               * Uncollateralized algorithmic stablecoins: 5-10
               * Non-redeemable, collateralized assets: 100
               * Redeemable assets: 200-400
    @param _fee Trade fee, given as an integer with 1e10 precision. The
                the maximum is 1% (100000000).
                50% of the fee is distributed to veCRV holders.
    @param _ma_exp_time Averaging window of oracle. Set as time_in_seconds // ln(2)
                        Example: for 10 minute EMA, _ma_exp_time is 600 // ln(2) ~= 866
    @param _implementation_idx Index of the implementation to use
    @param _asset_type Asset type for token, as an integer
    @param _method_id  First four bytes of the Keccak-256 hash of the function signatures
                       of the oracle addresses that gives rate oracles.
                       Calculated as: keccak(text=event_signature.replace(" ", ""))[:4]
    @param _oracle Rate oracle address.
    @return Address of the deployed pool
    """
    assert not self.base_pool_assets[_coin], "Invalid asset: Cannot pair base pool asset with base pool's LP token"
    assert _fee <= 100000000, "Invalid fee"
    assert _offpeg_fee_multiplier * _fee <= MAX_FEE * FEE_DENOMINATOR

    base_pool_n_coins: uint256 = len(self.base_pool_data[_base_pool].coins)
    assert base_pool_n_coins != 0, "Base pool is not added"

    implementation: address = self.metapool_implementations[_implementation_idx]
    assert implementation != empty(address), "Invalid implementation index"

    # things break if a token has >18 decimals
    decimals: uint256 = staticcall IERC20(_coin).decimals()
    assert decimals < 19, "Max 18 decimals for coins"

    # combine _coins's _asset_type and basepool coins _asset_types:
    base_pool_asset_types: DynArray[uint8, MAX_COINS] = self.base_pool_data[_base_pool].asset_types
    asset_types: DynArray[uint8, MAX_COINS]  = [_asset_type, 0]

    for i: uint256 in range(0, MAX_COINS):
        if i == base_pool_n_coins:
            break
        asset_types.append(base_pool_asset_types[i])

    _coins: DynArray[address, MAX_COINS] = [_coin, self.base_pool_data[_base_pool].lp_token]
    _rate_multipliers: DynArray[uint256, MAX_COINS] = [10 ** (36 - decimals), 10 ** 18]
    _method_ids: DynArray[bytes4, MAX_COINS] = [_method_id, empty(bytes4)]
    _oracles: DynArray[address, MAX_COINS] = [_oracle, empty(address)]

    pool: address = create_from_blueprint(
        implementation,
        _name,                                          # _name: String[32]
        _symbol,                                        # _symbol: String[10]
        _A,                                             # _A: uint256
        _fee,                                           # _fee: uint256
        _offpeg_fee_multiplier,                         # _offpeg_fee_multiplier: uint256
        _ma_exp_time,                                   # _ma_exp_time: uint256
        self.math_implementation,                       # _math_implementation: address
        _base_pool,                                     # _base_pool: address
        _coins,                                         # _coins: DynArray[address, MAX_COINS]
        self.base_pool_data[_base_pool].coins,          # base_coins: DynArray[address, MAX_COINS]
        _rate_multipliers,                              # _rate_multipliers: DynArray[uint256, MAX_COINS]
        asset_types,                                    # asset_types: DynArray[uint8, MAX_COINS]
        _method_ids,                                    # _method_ids: DynArray[bytes4, MAX_COINS]
        _oracles,                                       # _oracles: DynArray[address, MAX_COINS]
        code_offset=3
    )

    # add pool to pool_list
    length: uint256 = self.pool_count
    self.pool_list[length] = pool
    self.pool_count = length + 1

    base_lp_token: address = self.base_pool_data[_base_pool].lp_token

    self.pool_data[pool].decimals = [decimals, 18, 0, 0, 0, 0, 0, 0]
    self.pool_data[pool].n_coins = 2
    self.pool_data[pool].base_pool = _base_pool
    self.pool_data[pool].coins = [_coin, self.base_pool_data[_base_pool].lp_token]
    self.pool_data[pool].implementation = implementation

    is_finished: bool = False
    swappable_coin: address = empty(address)
    for i: uint256 in range(MAX_COINS):
        if i < len(self.base_pool_data[_base_pool].coins):
            swappable_coin = self.base_pool_data[_base_pool].coins[i]
        else:
            is_finished = True
            swappable_coin = base_lp_token

        key: uint256 = (convert(_coin, uint256) ^ convert(swappable_coin, uint256))
        length = self.market_counts[key]
        self.markets[key][length] = pool
        self.market_counts[key] = length + 1

        if is_finished:
            break

    log MetaPoolDeployed(pool=pool, coin=_coin, base_pool=_base_pool, A=_A, fee=_fee, deployer=msg.sender)
    return pool


@external
def deploy_gauge(_pool: address) -> address:
    """
    @notice Deploy a liquidity gauge for a factory pool
    @param _pool Factory pool address to deploy a gauge for
    @return Address of the deployed gauge
    """
    assert self.pool_data[_pool].coins[0] != empty(address), "Unknown pool"
    assert self.pool_data[_pool].liquidity_gauge == empty(address), "Gauge already deployed"
    implementation: address = self.gauge_implementation
    assert implementation != empty(address), "Gauge implementation not set"

    gauge: address = create_from_blueprint(self.gauge_implementation, _pool, code_offset=3)
    self.pool_data[_pool].liquidity_gauge = gauge

    log LiquidityGaugeDeployed(pool=_pool, gauge=gauge)
    return gauge


# <--- Admin // Guarded Functionality --->

@external
def add_base_pool(
    _base_pool: address,
    _base_lp_token: address,
    _asset_types: DynArray[uint8, MAX_COINS],
    _n_coins: uint256,
):
    """
    @notice Add a base pool to the registry, which may be used in factory metapools
    @dev 1. Only callable by admin
         2. Rebasing tokens are not allowed in the base pool.
         3. Do not add base pool which contains native tokens (e.g. ETH).
         4. As much as possible: use standard IERC20 tokens.
         Should you choose to deviate from these recommendations, audits are advised.
    @param _base_pool Pool address to add
    @param _asset_types Asset type for pool, as an integer
    """
    assert msg.sender == self.admin  # dev: admin-only function
    assert 2 not in _asset_types  # dev: rebasing tokens cannot be in base pool
    assert len(self.base_pool_data[_base_pool].coins) == 0  # dev: pool exists
    assert _n_coins < MAX_COINS  # dev: base pool can only have (MAX_COINS - 1) coins.

    # add pool to pool_list
    length: uint256 = self.base_pool_count
    self.base_pool_list[length] = _base_pool
    self.base_pool_count = length + 1
    self.base_pool_data[_base_pool].lp_token = _base_lp_token
    self.base_pool_data[_base_pool].n_coins = _n_coins
    self.base_pool_data[_base_pool].asset_types = _asset_types

    decimals: uint256 = 0
    coins: DynArray[address, MAX_COINS] = empty(DynArray[address, MAX_COINS])
    coin: address = empty(address)
    for i: uint256 in range(MAX_COINS):
        if i == _n_coins:
            break
        coin = staticcall CurvePool(_base_pool).coins(i)
        assert coin != 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE  # dev: native token is not supported
        self.base_pool_data[_base_pool].coins.append(coin)
        self.base_pool_assets[coin] = True
        decimals += (staticcall IERC20(coin).decimals() << i*8)
    self.base_pool_data[_base_pool].decimals = decimals

    log BasePoolAdded(base_pool=_base_pool)


@external
def set_pool_implementations(
    _implementation_index: uint256,
    _implementation: address,
):
    """
    @notice Set implementation contracts for pools
    @dev Only callable by admin
    @param _implementation_index Implementation index where implementation is stored
    @param _implementation Implementation address to use when deploying plain pools
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.pool_implementations[_implementation_index] = _implementation


@external
def set_metapool_implementations(
    _implementation_index: uint256,
    _implementation: address,
):
    """
    @notice Set implementation contracts for metapools
    @dev Only callable by admin
    @param _implementation_index Implementation index where implementation is stored
    @param _implementation Implementation address to use when deploying meta pools
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.metapool_implementations[_implementation_index] = _implementation


@external
def set_math_implementation(_math_implementation: address):
    """
    @notice Set implementation contracts for StableSwap Math
    @dev Only callable by admin
    @param _math_implementation Address of the math implementation contract
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.math_implementation = _math_implementation


@external
def set_gauge_implementation(_gauge_implementation: address):
    """
    @notice Set implementation contracts for liquidity gauge
    @dev Only callable by admin
    @param _gauge_implementation Address of the gauge blueprint implementation contract
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.gauge_implementation = _gauge_implementation


@external
def set_views_implementation(_views_implementation: address):
    """
    @notice Set implementation contracts for Views methods
    @dev Only callable by admin
    @param _views_implementation Implementation address of views contract
    """
    assert msg.sender == self.admin  # dev: admin-only function
    self.views_implementation = _views_implementation


@external
def commit_transfer_ownership(_addr: address):
    """
    @notice Transfer ownership of this contract to `addr`
    @param _addr Address of the new owner
    """
    assert msg.sender == self.admin  # dev: admin only
    self.future_admin = _addr


@external
def accept_transfer_ownership():
    """
    @notice Accept a pending ownership transfer
    @dev Only callable by the new owner
    """
    _admin: address = self.future_admin
    assert msg.sender == _admin  # dev: future admin only

    self.admin = _admin
    self.future_admin = empty(address)


@external
def set_fee_receiver(_pool: address, _fee_receiver: address):
    """
    @notice Set fee receiver for all pools
    @param _pool Address of  pool to set fee receiver for.
    @param _fee_receiver Address that fees are sent to
    """
    assert msg.sender == self.admin  # dev: admin only
    self.fee_receiver = _fee_receiver


@external
def add_asset_type(_id: uint8, _name: String[10]):
    """
    @notice Admin only method that adds a new asset type.
    @param _id asset type id.
    @param _name Name of the asset type.
    """
    assert msg.sender == self.admin  # dev: admin only
    self.asset_types[_id] = _name
