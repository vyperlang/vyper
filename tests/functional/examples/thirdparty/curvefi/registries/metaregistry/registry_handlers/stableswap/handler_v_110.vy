# pragma version >=0.4.2
"""
@title CurveStableswapFactoryNGHandler
@custom:version 1.1.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Stableswap Factory handler for the Metaregistry
"""

version: public(constant(String[8])) = "1.1.0"


# ---- interfaces ---- #
interface BaseRegistry:
    def find_pool_for_coins(_from: address, _to: address, i: uint256 = ...) -> address: view
    def get_admin_balances(_pool: address) -> DynArray[uint256, MAX_METAREGISTRY_COINS]: view
    def get_A(_pool: address) -> uint256: view
    def get_balances(_pool: address) -> DynArray[uint256, MAX_METAREGISTRY_COINS]: view
    def get_coins(_pool: address) -> DynArray[address, MAX_METAREGISTRY_COINS]: view
    def get_coin_indices(_pool: address, _from: address, _to: address) -> (int128, int128): view
    def get_decimals(_pool: address) -> DynArray[uint256, MAX_METAREGISTRY_COINS]: view
    def get_fees(_pool: address) -> uint256[2]: view
    def get_gauge(_pool: address) -> address: view
    def get_lp_token(_pool: address) -> address: view
    def get_meta_n_coins(_pool: address) -> (uint256, uint256): view
    def get_n_coins(_pool: address) -> uint256: view
    def get_pool_asset_type(_pool: address) -> uint256: view
    def get_underlying_balances(_pool: address) -> DynArray[uint256, MAX_METAREGISTRY_COINS]: view
    def get_underlying_coins(_pool: address) -> DynArray[address, MAX_METAREGISTRY_COINS]: view
    def get_underlying_decimals(_pool: address) -> DynArray[uint256, MAX_METAREGISTRY_COINS]: view
    def is_meta(_pool: address) -> bool: view
    def pool_count() -> uint256: view
    def pool_list(pool_id: uint256) -> address: view
    def base_pool_data(_pool: address) -> BasePoolArray: view
    def base_pool_count() -> uint256: view
    def get_base_pool(_pool: address) -> address: view
    def base_pool_list(i: uint256) -> address: view

interface CurvePool:
    def admin_balances(i: uint256) -> uint256: view
    def balances(i: uint256) -> uint256: view
    def get_virtual_price() -> uint256: view
    def fee() -> uint256: view
    def admin_fee() -> uint256: view
    def offpeg_fee_multiplier() -> uint256: view
    def coins(i: uint256) -> address: view

interface IERC20:
    def balanceOf(_addr: address) -> uint256: view
    def decimals() -> uint256: view
    def name() -> String[64]: view
    def totalSupply() -> uint256: view

interface Gauge:
    def is_killed() -> bool: view


struct BasePoolArray:
    lp_token: address
    coins: DynArray[address, MAX_METAREGISTRY_COINS]
    decimals: uint256
    n_coins: uint256
    asset_types: DynArray[uint8, MAX_METAREGISTRY_COINS]


# ---- constants ---- #
MAX_METAREGISTRY_COINS: constant(uint256) = 8

# ---- storage variables ---- #
base_registry: public(BaseRegistry)


# ---- constructor ---- #
@deploy
def __init__(_registry_address: address):
    self.base_registry = BaseRegistry(_registry_address)


# ---- internal methods ---- #
@internal
@view
def _get_base_pool_lp_token(_lp_token: address) -> address:
    for i: uint256 in range(staticcall self.base_registry.base_pool_count(), bound=10000):
        base_pool: address = staticcall self.base_registry.base_pool_list(i)
        if (staticcall self.base_registry.base_pool_data(base_pool)).lp_token == _lp_token:
            return base_pool
    return empty(address)


@internal
@view
def _get_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    _coins: DynArray[address, MAX_METAREGISTRY_COINS] = staticcall self.base_registry.get_coins(_pool)
    _padded_coins: address[MAX_METAREGISTRY_COINS] = empty(address[MAX_METAREGISTRY_COINS])
    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if i == len(_coins):
            break
        _padded_coins[i] = _coins[i]
    return _padded_coins


@internal
@view
def _get_underlying_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    _coins: DynArray[address, MAX_METAREGISTRY_COINS] = staticcall self.base_registry.get_underlying_coins(_pool)
    _padded_coins: address[MAX_METAREGISTRY_COINS] = empty(address[MAX_METAREGISTRY_COINS])
    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if i == len(_coins):
            break
        _padded_coins[i] = _coins[i]
    return _padded_coins


@view
@internal
def _get_meta_underlying_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    base_coin_idx: uint256 = staticcall self.base_registry.get_n_coins(_pool) - 1
    base_pool: address = staticcall self.base_registry.get_base_pool(_pool)

    # base pool lp token is at index 1:
    base_total_supply: uint256 = staticcall IERC20(staticcall CurvePool(_pool).coins(1)).totalSupply()

    ul_balance: uint256 = 0
    underlying_pct: uint256 = 0
    if base_total_supply > 0:
        underlying_pct = staticcall CurvePool(_pool).balances(base_coin_idx) * 10**36 // base_total_supply

    underlying_balances: uint256[MAX_METAREGISTRY_COINS] = empty(uint256[MAX_METAREGISTRY_COINS])
    ul_coins: address[MAX_METAREGISTRY_COINS] = self._get_underlying_coins(_pool)

    for i: uint256 in range(MAX_METAREGISTRY_COINS):

        if ul_coins[i] == empty(address):
            break

        if i < base_coin_idx:
            ul_balance = staticcall CurvePool(_pool).balances(i)

        else:
            ul_balance = staticcall CurvePool(base_pool).balances(i - base_coin_idx)
            ul_balance = ul_balance * underlying_pct // 10**36
        underlying_balances[i] = ul_balance

    return underlying_balances


@internal
@view
def _pad_uint_dynarray(
    _array: DynArray[uint256, MAX_METAREGISTRY_COINS]
) -> uint256[MAX_METAREGISTRY_COINS]:
    _padded_array: uint256[MAX_METAREGISTRY_COINS] = empty(uint256[MAX_METAREGISTRY_COINS])
    array_len: uint256 = len(_array)
    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if i == array_len:
            break
        _padded_array[i] = _array[i]
    return _padded_array


@internal
@view
def _pad_addr_dynarray(_array: DynArray[address, MAX_METAREGISTRY_COINS]) -> address[MAX_METAREGISTRY_COINS]:
    _padded_array: address[MAX_METAREGISTRY_COINS] = empty(address[MAX_METAREGISTRY_COINS])
    array_len: uint256 = len(_array)
    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if i == array_len:
            break
        _padded_array[i] = _array[i]
    return _padded_array


# ---- view methods (API) of the contract ---- #
@external
@view
def find_pool_for_coins(_from: address, _to: address, i: uint256 = 0) -> address:
    return staticcall self.base_registry.find_pool_for_coins(_from, _to, i)


@external
@view
def get_admin_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the balances of the admin of the pool
    @dev does not use base registry admin_balances because that has errors
         in the getter for n_coins (some pools show zero, so admin balances is zero)
    @param _pool address of the pool
    @return balances of the admin of the pool
    """
    n_coins: uint256 = staticcall self.base_registry.get_n_coins(_pool)
    admin_balances: uint256[MAX_METAREGISTRY_COINS] = empty(uint256[MAX_METAREGISTRY_COINS])
    for i: uint256 in range(MAX_METAREGISTRY_COINS):
        if i == n_coins:
            break
        admin_balances[i] = staticcall CurvePool(_pool).admin_balances(i)
    return admin_balances


@external
@view
def get_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the balances of the pool
    @param _pool address of the pool
    @return balances of the pool
    """
    return self._pad_uint_dynarray(staticcall self.base_registry.get_balances(_pool))


@external
@view
def get_base_pool(_pool: address) -> address:
    """
    @notice Get the base pool of the pool
    @param _pool address of the pool
    @return base pool of the pool
    """
    return staticcall self.base_registry.get_base_pool(_pool)


@view
@external
def get_coin_indices(_pool: address, _from: address, _to: address) -> (int128, int128, bool):
    """
    @notice Get the indices of the coins in the pool
    @param _pool address of the pool
    @param _from address of the coin
    @param _to address of the coin
    @return coin indices and whether the coin swap involves an underlying market or not
    """
    coin1: int128 = 0
    coin2: int128 = 0
    is_underlying: bool = False

    (coin1, coin2) = staticcall self.base_registry.get_coin_indices(_pool, _from, _to)

    # due to a bug in original factory contract, `is_underlying`` is always True
    # to fix this, we first check if it is a metapool, and if not then we return
    # False. If so, then we check if basepool lp token is one of the two coins,
    # in which case `is_underlying` would be False
    if staticcall self.base_registry.is_meta(_pool):
        base_pool_lp_token: address = (staticcall self.base_registry.get_coins(_pool))[1]
        if base_pool_lp_token not in [_from, _to]:
            is_underlying = True

    return (coin1, coin2, is_underlying)


@external
@view
def get_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the coins of the pool
    @param _pool address of the pool
    @return coins of the pool
    """
    return self._get_coins(_pool)


@external
@view
def get_decimals(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the decimals of coins in the pool
    @param _pool address of the pool
    @return decimals of coins in the pool
    """
    return self._pad_uint_dynarray(staticcall self.base_registry.get_decimals(_pool))


@external
@view
def get_fees(_pool: address) -> uint256[10]:
    """
    @notice Get the fees of the pool
    @param _pool address of the pool
    @return fees of the pool
    """
    fees: uint256[10] = empty(uint256[10])
    fees[0] = staticcall CurvePool(_pool).fee()
    fees[1] = staticcall CurvePool(_pool).admin_fee()
    fees[2] = staticcall CurvePool(_pool).offpeg_fee_multiplier()
    return fees


@external
@view
def get_virtual_price_from_lp_token(_pool: address) -> uint256:
    """
    @notice Get the virtual price of the pool
    @param _pool address of the pool
    @return virtual price of the pool
    """
    return staticcall CurvePool(_pool).get_virtual_price()


@external
@view
def get_lp_token(_pool: address) -> address:
    """
    @notice Get the lp token of the pool
    @dev for stableswap factory pools, the pool is the lp token itself
    @param _pool address of the pool
    @return lp token of the pool
    """
    return _pool


@external
@view
def get_n_coins(_pool: address) -> uint256:
    """
    @notice Get the number of coins in the pool
    @param _pool address of the pool
    @return number of coins in the pool
    """
    return staticcall self.base_registry.get_n_coins(_pool)


@external
@view
def get_n_underlying_coins(_pool: address) -> uint256:
    """
    @notice Get the number of underlying coins in the pool
    @param _pool address of the pool
    @return number of underlying coins in the pool
    """
    # need to check if any of the token is a base pool LP token
    # since a metapool can be lptoken:lptoken, and it would count
    # underlying coins as 1 + base_pool_n_coins instead of 2 x base_pool_n_coins
    coins: address[MAX_METAREGISTRY_COINS] = self._get_coins(_pool)
    base_pool: address = empty(address)
    num_coins: uint256 = 0
    for i: uint256 in range(MAX_METAREGISTRY_COINS):

        if coins[i] == empty(address):
            break

        base_pool = staticcall self.base_registry.get_base_pool(coins[i])
        if base_pool == empty(address) and coins[i] != empty(address):
            num_coins += 1
        else:
            num_coins += (staticcall self.base_registry.base_pool_data(base_pool)).n_coins

    return num_coins


@external
@view
def get_pool_asset_type(_pool: address) -> uint256:
    """
    @notice Get the asset type of the coins in the pool
    @dev 0 = USD, 1 = ETH, 2 = BTC, 3 = Other
    @param _pool address of the pool
    @return pool asset type of the pool
    """
    return staticcall self.base_registry.get_pool_asset_type(_pool)


@external
@view
def get_pool_from_lp_token(_lp_token: address) -> address:
    """
    @notice Get the pool of the lp token
    @dev This is more or less like a pass through method. Can be ignored but
         We leave it in for consistency across registry handlers.
    @param _lp_token address of the lp token (which is also the pool)
    @return pool of the lp token
    """
    if staticcall self.base_registry.get_n_coins(_lp_token) > 0:
        return _lp_token
    return empty(address)


@external
@view
def get_pool_name(_pool: address) -> String[64]:
    """
    @notice Get the name of the pool
    @dev stable factory pools are IERC20 tokenized
    @return name of the pool
    """
    if staticcall self.base_registry.get_n_coins(_pool) == 0:
        # _pool is not in base registry, so we ignore:
        return ""
    return staticcall IERC20(_pool).name()


@external
@view
def get_pool_params(_pool: address) -> uint256[20]:
    """
    @notice Get the parameters of the pool
    @param _pool address of the pool
    @return parameters of the pool
    """
    stableswap_pool_params: uint256[20] = empty(uint256[20])
    stableswap_pool_params[0] = staticcall self.base_registry.get_A(_pool)
    return stableswap_pool_params


@external
@view
def get_underlying_balances(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the underlying balances of the pool
    @param _pool address of the pool
    @return underlying balances of the pool
    """
    if not staticcall self.base_registry.is_meta(_pool):
        return self._pad_uint_dynarray(staticcall self.base_registry.get_balances(_pool))
    return self._get_meta_underlying_balances(_pool)


@external
@view
def get_underlying_coins(_pool: address) -> address[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the underlying coins of the pool
    @param _pool address of the pool
    @return underlying coins of the pool
    """
    if not staticcall self.base_registry.is_meta(_pool):
        return self._get_coins(_pool)
    return self._get_underlying_coins(_pool)


@external
@view
def get_underlying_decimals(_pool: address) -> uint256[MAX_METAREGISTRY_COINS]:
    """
    @notice Get the underlying decimals of the pool
    @dev If it is a metapool, method uses the base registry. Else it uses a
         custom getter. This is because the base registry cannot unpack decimals
         (stored as a bitmap) if there is no metapool. So it returns the decimals of
         only the first coin.
    @param _pool Address of the pool
    @return underlying decimals of the pool
    """
    if not staticcall self.base_registry.is_meta(_pool):
        return self._pad_uint_dynarray(staticcall self.base_registry.get_decimals(_pool))
    return self._pad_uint_dynarray(staticcall self.base_registry.get_underlying_decimals(_pool))


@external
@view
def is_meta(_pool: address) -> bool:
    """
    @notice Check if the pool is a metapool
    @param _pool address of the pool
    @return True if the pool is a metapool
    """
    return staticcall self.base_registry.is_meta(_pool)


@external
@view
def is_registered(_pool: address) -> bool:
    """
    @notice Check if a pool belongs to the registry using get_n_coins
    @param _pool The address of the pool
    @return A bool corresponding to whether the pool belongs or not
    """
    return staticcall self.base_registry.get_n_coins(_pool) > 0


@external
@view
def pool_count() -> uint256:
    """
    @notice Get the number of pools in the registry
    @return number of pools in the registry
    """
    return staticcall self.base_registry.pool_count()


@external
@view
def pool_list(_index: uint256) -> address:
    """
    @notice Get the address of the pool at the given index
    @param _index The index of the pool
    @return The address of the pool
    """
    return staticcall self.base_registry.pool_list(_index)
