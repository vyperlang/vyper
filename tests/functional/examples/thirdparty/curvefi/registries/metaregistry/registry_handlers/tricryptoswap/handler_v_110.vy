# pragma version >=0.4.2
"""
@title CurveTricryptoSwapFactoryHandler
@custom:version 1.1.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice TricryptoSwap Factory Handler for the MetaRegistry
"""

version: public(constant(String[8])) = "1.1.0"


interface BaseRegistry:
    def find_pool_for_coins(_from: address, _to: address, i: uint256 = ...) -> address: view
    def get_coin_indices(_pool: address, _from: address, _to: address) -> (uint256, uint256): view
    def get_balances(_pool: address) -> uint256[MAX_COINS]: view
    def get_coins(_pool: address) -> address[MAX_COINS]: view
    def get_decimals(_pool: address) -> uint256[MAX_COINS]: view
    def get_gauge(_pool: address) -> address: view
    def get_n_coins(_pool: address) -> uint256: view
    def get_token(_pool: address) -> address: view
    def pool_count() -> uint256: view
    def pool_list(pool_id: uint256) -> address: view

interface TricryptoNG:
    def adjustment_step() -> uint256: view
    def ADMIN_FEE() -> uint256: view
    def allowed_extra_profit() -> uint256: view
    def A() -> uint256: view
    def balances(i: uint256) -> uint256: view
    def D() -> uint256: view
    def fee() -> uint256: view
    def fee_gamma() -> uint256: view
    def gamma() -> uint256: view
    def get_virtual_price() -> uint256: view
    def ma_time() -> uint256: view
    def mid_fee() -> uint256: view
    def out_fee() -> uint256: view
    def virtual_price() -> uint256: view
    def xcp_profit() -> uint256: view
    def xcp_profit_a() -> uint256: view

interface IERC20:
    def name() -> String[64]: view
    def balanceOf(_addr: address) -> uint256: view
    def totalSupply() -> uint256: view
    def decimals() -> uint256: view

interface GaugeController:
    def gauge_types(gauge: address) -> int128: view
    def gauges(i: uint256) -> address: view

interface Gauge:
    def is_killed() -> bool: view


# ---- constants ---- #
MAX_COINS: constant(uint256) = 3
MAX_METAREGISTRY_COINS: constant(uint256) = 8
MAX_POOLS: constant(uint256) = 65536
N_COINS: constant(uint256) = 3


# ---- storage variables ---- #
base_registry: public(BaseRegistry)


# ---- constructor ---- #
@deploy
def __init__(_registry_address: address):
    self.base_registry = BaseRegistry(_registry_address)


# ---- internal methods ---- #
@internal
@view
def _pad_uint_array(_array: uint256[MAX_COINS]) -> uint256[MAX_METAREGISTRY_COINS]:
    _padded_array: uint256[MAX_METAREGISTRY_COINS] = empty(uint256[MAX_METAREGISTRY_COINS])
    for i: uint256 in range(MAX_COINS):
        _padded_array[i] = _array[i]
    return _padded_array


@internal
@view
def _get_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    return self._pad_uint_array(staticcall self.base_registry.get_balances(_pool))


@internal
@view
def _get_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    _coins: address[MAX_COINS] = staticcall self.base_registry.get_coins(_pool)
    _padded_coins: address[MAX_METAREGISTRY_COINS] = empty(address[MAX_METAREGISTRY_COINS])
    for i: uint256 in range(MAX_COINS):
        _padded_coins[i] = _coins[i]
    return _padded_coins


@internal
@view
def _get_decimals(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    return self._pad_uint_array(staticcall self.base_registry.get_decimals(_pool))


@internal
@view
def _get_n_coins(_pool: address) -> uint256:

    if (staticcall self.base_registry.get_coins(_pool))[0] != empty(address):
        return N_COINS
    return 0


@internal
@view
def _is_registered(_pool: address) -> bool:
    return self._get_n_coins(_pool) > 0


# ---- view methods (API) of the contract ---- #
@external
@view
def find_pool_for_coins(_from: address, _to: address, i: uint256 = 0) -> address:
    """
    @notice checks if either of the two coins are in a base pool and then checks
            if the basepool lp token and the other coin have a pool.
            This is done because the factory does not have `underlying` methods in
            pools that have a basepool lp token in them
    @param _from Address of the _from coin
    @param _to Address of the _to coin
    @param i Index of the pool to return
    @return Address of the pool
    """
    return staticcall self.base_registry.find_pool_for_coins(_from, _to, i)


@external
@view
def get_admin_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the balances of the admin tokens of the given pool
    @dev Cryptoswap pools do not store admin fees in the form of
         admin token balances. Instead, the admin fees are computed
         at the time of claim iff sufficient profits have been made.
         These fees are allocated to the admin by minting LP tokens
         (dilution). The logic to calculate fees are derived from
         cryptopool._claim_admin_fees() method.
    @param _pool Address of the pool
    @return uint256[MAX_METAREGISTRY_COINS] Array of admin balances
    """

    xcp_profit: uint256 = staticcall TricryptoNG(_pool).xcp_profit()
    xcp_profit_a: uint256 = staticcall TricryptoNG(_pool).xcp_profit_a()
    admin_fee: uint256 = staticcall TricryptoNG(_pool).ADMIN_FEE()
    admin_balances: uint256[MAX_METAREGISTRY_COINS] = empty(uint256[MAX_METAREGISTRY_COINS])

    # admin balances are non zero if pool has made more than allowed profits:
    if xcp_profit > xcp_profit_a:

        # calculate admin fees in lp token amounts:
        fees: uint256 = (xcp_profit - xcp_profit_a) * admin_fee // (2 * 10**10)
        if fees > 0:
            vprice: uint256 = staticcall TricryptoNG(_pool).virtual_price()
            frac: uint256 = vprice * 10**18 // (vprice - fees) - 10**18

            # the total supply of lp token is current supply + claimable:
            lp_token_total_supply: uint256 = staticcall IERC20(_pool).totalSupply()
            d_supply: uint256 = lp_token_total_supply * frac // 10**18
            lp_token_total_supply += d_supply
            admin_lp_frac: uint256 = d_supply * 10 ** 18 // lp_token_total_supply

            # get admin balances in individual assets:
            reserves: uint256[MAX_METAREGISTRY_COINS] = self._get_balances(_pool)
            for i: uint256 in range(MAX_METAREGISTRY_COINS):
                admin_balances[i] = admin_lp_frac * reserves[i] // 10 ** 18

    return admin_balances


@external
@view
def get_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the balances of the tokens of the given pool
    @param _pool Address of the pool
    @return uint256[MAX_METAREGISTRY_COINS] Array of balances
    """
    return self._get_balances(_pool)


@external
@view
def get_base_pool(_pool: address) -> address:
    """
    @notice Returns the base pool of the given pool
    @dev Returns empty(address) if the pool isn't a metapool
    @param _pool Address of the pool
    @return Address of the base pool
    """
    return empty(address)


@external
@view
def get_coin_indices(_pool: address, _from: address, _to: address) -> (uint256, uint256, bool):
    """
    @notice Convert coin addresses to indices for use with pool methods
    @param _pool Address of the pool
    @param _from Address of the from coin
    @param _to Address of the to coin
    @return (uint256, uint256, bool) Tuple of indices of the coins in the pool,
            and whether the market is an underlying market or not.
    """
    i: uint256 = 0
    j: uint256 = 0

    (i, j) = staticcall self.base_registry.get_coin_indices(_pool, _from, _to)

    return (i, j, False)


@external
@view
def get_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the coins of the given pool
    @param _pool Address of the pool
    @return address[MAX_METAREGISTRY_COINS] Array of coins
    """
    return self._get_coins(_pool)


@external
@view
def get_decimals(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the decimals of the coins in a given pool
    @param _pool Address of the pool
    @return uint256[MAX_METAREGISTRY_COINS] Array of decimals
    """
    return self._get_decimals(_pool)


@external
@view
def get_fees(_pool: address) -> uint256[10]:
    """
    @notice Returns the fees of the given pool
    @param _pool Address of the pool
    @return uint256[10] Array of fees. Fees are arranged as:
            1. swap fee (or `fee`)
            2. admin fee
            3. mid fee (fee when cryptoswap pool is pegged)
            4. out fee (fee when cryptoswap pool depegs)
    """
    fees: uint256[10] = empty(uint256[10])
    pool_fees: uint256[4] = [
        staticcall TricryptoNG(_pool).fee(),
        staticcall TricryptoNG(_pool).ADMIN_FEE(),
        staticcall TricryptoNG(_pool).mid_fee(),
        staticcall TricryptoNG(_pool).out_fee(),
    ]
    for i: uint256 in range(4):
        fees[i] = pool_fees[i]
    return fees


@external
@view
def get_lp_token(_pool: address) -> address:
    """
    @notice Returns the Liquidity Provider token of the given pool
    @param _pool Address of the pool
    @return Address of the Liquidity Provider token
    """
    return _pool


@external
@view
def get_n_coins(_pool: address) -> uint256:
    """
    @notice Returns the number of coins in the given pool
    @param _pool Address of the pool
    @return uint256 Number of coins
    """
    return self._get_n_coins(_pool)


@external
@view
def get_n_underlying_coins(_pool: address) -> uint256:
    """
    @notice Get the number of underlying coins in a pool
    @param _pool Address of the pool
    @return uint256 Number of underlying coins
    """
    _coins: address[MAX_METAREGISTRY_COINS] = self._get_coins(_pool)

    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if _coins[i] == empty(address):
            return i
    raise

@external
@view
def get_pool_asset_type(_pool: address) -> uint256:
    """
    @notice Returns the asset type of the given pool
    @dev Returns 4: 0 = USD, 1 = ETH, 2 = BTC, 3 = Other
    @param _pool Address of the pool
    @return uint256 Asset type
    """
    return 3


@external
@view
def get_pool_from_lp_token(_lp_token: address) -> address:
    """
    @notice Returns the pool of the given Liquidity Provider token
    @param _lp_token Address of the Liquidity Provider token
    @return Address of the pool
    """
    if self._get_n_coins(_lp_token) > 0:
        return _lp_token
    return empty(address)


@external
@view
def get_pool_name(_pool: address) -> String[64]:
    """
    @notice Returns the name of the given pool
    @param _pool Address of the pool
    @return String[64] Name of the pool
    """
    return staticcall IERC20(staticcall self.base_registry.get_token(_pool)).name()

@external
@view
def get_pool_params(_pool: address) -> uint256[20]:
    """
    @notice returns pool params given a cryptopool address
    @dev contains all settable parameter that alter the pool's performance
    @dev only applicable for cryptopools
    @param _pool Address of the pool for which data is being queried.
    """
    pool_params: uint256[20] = empty(uint256[20])
    pool_params[0] = staticcall TricryptoNG(_pool).A()
    pool_params[1] = staticcall TricryptoNG(_pool).D()
    pool_params[2] = staticcall TricryptoNG(_pool).gamma()
    pool_params[3] = staticcall TricryptoNG(_pool).allowed_extra_profit()
    pool_params[4] = staticcall TricryptoNG(_pool).fee_gamma()
    pool_params[5] = staticcall TricryptoNG(_pool).adjustment_step()
    pool_params[6] = staticcall TricryptoNG(_pool).ma_time()
    return pool_params


@external
@view
def get_underlying_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the underlying balances of the given pool
    @param _pool Address of the pool
    @return uint256[MAX_METAREGISTRY_COINS] Array of underlying balances
    """
    return self._get_balances(_pool)


@external
@view
def get_underlying_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the underlying coins of the given pool
    @param _pool Address of the pool
    @return address[MAX_METAREGISTRY_COINS] Array of underlying coins
    """
    return self._get_coins(_pool)


@external
@view
def get_underlying_decimals(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Returns the underlying decimals of the given pool
    @param _pool Address of the pool
    @return uint256[MAX_METAREGISTRY_COINS] Array of underlying decimals
    """
    return self._get_decimals(_pool)


@external
@view
def get_virtual_price_from_lp_token(_token: address) -> uint256:
    """
    @notice Returns the virtual price of the given Liquidity Provider token
    @param _token Address of the Liquidity Provider token
    @return uint256 Virtual price
    """
    return staticcall TricryptoNG(_token).get_virtual_price()


@external
@view
def is_meta(_pool: address) -> bool:
    """
    @notice Returns whether the given pool is a meta pool
    @param _pool Address of the pool
    @return bool Whether the pool is a meta pool
    """
    return False


@external
@view
def is_registered(_pool: address) -> bool:
    """
    @notice Check if a pool belongs to the registry using get_n_coins
    @param _pool The address of the pool
    @return A bool corresponding to whether the pool belongs or not
    """
    return self._get_n_coins(_pool) > 0


@external
@view
def pool_count() -> uint256:
    """
    @notice Returns the number of pools in the registry
    @return uint256 Number of pools
    """
    return staticcall self.base_registry.pool_count()


@external
@view
def pool_list(_index: uint256) -> address:
    """
    @notice Returns the address of the pool at the given index
    @param _index Index of the pool
    @return Address of the pool
    """
    return staticcall self.base_registry.pool_list(_index)
