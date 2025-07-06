# pragma version >=0.4.2
# pragma evm-version paris
"""
@title CurveRateProvider
@custom:version 1.0.1
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Provides quotes for coin pairs, iff coin pair is in a Curve AMM that the Metaregistry recognises.
"""

version: public(constant(String[8])) = "1.0.1"

from ethereum.ercs import IERC20Detailed

MAX_COINS: constant(uint256) = 8
MAX_QUOTES: constant(uint256) = 100

struct Quote:
    source_token_index: uint256
    dest_token_index: uint256
    is_underlying: bool
    amount_out: uint256
    pool: address
    source_token_pool_balance: uint256
    dest_token_pool_balance: uint256
    pool_type: uint8  # 0 for stableswap, 1 for cryptoswap, 2 for LLAMMA.


# Interfaces

interface AddressProvider:
    def get_address(id: uint256) -> address: view

interface Metaregistry:
    def find_pools_for_coins(source_coin: address, destination_coin: address) -> DynArray[address, 1000]: view
    def get_coin_indices(_pool: address, _from: address, _to: address) -> (int128, int128, bool): view
    def get_underlying_balances(_pool: address) -> uint256[MAX_COINS]: view


ADDRESS_PROVIDER: public(immutable(AddressProvider))
METAREGISTRY_ID: constant(uint256) = 7
STABLESWAP_META_ABI: constant(String[64]) = "get_dy_underlying(int128,int128,uint256)"
STABLESWAP_ABI: constant(String[64]) = "get_dy(int128,int128,uint256)"
CRYPTOSWAP_ABI: constant(String[64]) = "get_dy(uint256,uint256,uint256)"

@deploy
def __init__(address_provider: address):
    ADDRESS_PROVIDER = AddressProvider(address_provider)


@external
@view
def get_quotes(source_token: address, destination_token: address, amount_in: uint256) -> DynArray[Quote, MAX_QUOTES]:
    return self._get_quotes(source_token, destination_token, amount_in)


@external
@view
def get_aggregated_rate(source_token: address, destination_token: address) -> uint256:

    amount_in: uint256 = 10**convert(staticcall IERC20Detailed(source_token).decimals(), uint256)
    quotes: DynArray[Quote, MAX_QUOTES] = self._get_quotes(source_token, destination_token, amount_in)

    return self.weighted_average_quote(
        convert(staticcall IERC20Detailed(source_token).decimals(), uint256), 
        convert(staticcall IERC20Detailed(destination_token).decimals(), uint256),
        quotes, 
    )


@internal
@pure
def weighted_average_quote(
    source_token_decimals: uint256, 
    dest_token_decimals: uint256, 
    quotes: DynArray[Quote, MAX_QUOTES]
) -> uint256:
    
    num_quotes: uint256 = len(quotes)

    # Calculate total balance with normalization
    total_balance: uint256 = 0
    for i: uint256 in range(num_quotes, bound=MAX_QUOTES):
        source_balance_normalized: uint256 = quotes[i].source_token_pool_balance * 10**(18 - source_token_decimals)
        dest_balance_normalized: uint256 = quotes[i].dest_token_pool_balance * 10**(18 - dest_token_decimals)
        total_balance += source_balance_normalized + dest_balance_normalized


    # Calculate weighted sum with normalization
    weighted_avg: uint256 = 0
    for i: uint256 in range(num_quotes, bound=MAX_QUOTES):
        source_balance_normalized: uint256 = quotes[i].source_token_pool_balance * 10**(18 - source_token_decimals)
        dest_balance_normalized: uint256 = quotes[i].dest_token_pool_balance * 10**(18 - dest_token_decimals)
        pool_balance_normalized: uint256 = source_balance_normalized + dest_balance_normalized
        weight: uint256 = (pool_balance_normalized * 10**18) // total_balance  # Use 18 decimal places for precision
        weighted_avg += weight * quotes[i].amount_out // 10**18

    return weighted_avg


@internal
@view
def _get_quotes(source_token: address, destination_token: address, amount_in: uint256) -> DynArray[Quote, MAX_QUOTES]:

    quotes: DynArray[Quote, MAX_QUOTES] = []
    metaregistry: Metaregistry = Metaregistry(staticcall ADDRESS_PROVIDER.get_address(METAREGISTRY_ID))
    pools: DynArray[address, 1000] = staticcall metaregistry.find_pools_for_coins(source_token, destination_token)

    if len(pools) == 0:
        return quotes

    # get pool types for each pool
    for pool: address in pools:

        # is it a stableswap pool? are the coin pairs part of a metapool?
        pool_type: uint8 = self._get_pool_type(pool, metaregistry)

        # get coin indices
        i: int128 = 0
        j: int128 = 0
        is_underlying: bool = False
        (i, j, is_underlying) = staticcall metaregistry.get_coin_indices(pool, source_token, destination_token)

        # get balances
        balances: uint256[MAX_COINS] = staticcall metaregistry.get_underlying_balances(pool)
        balances_i: uint256 = balances[i]
        balances_j: uint256 = balances[j]

        # skip if pool is too small or if amount_in is zero
        if 0 in [balances_i, balances_j] or amount_in == 0:
            continue

        # do a get_dy call and only save quote if call does not bork; use correct abi (in128 vs uint256)
        quote: uint256 = self._get_pool_quote(i, j, amount_in, pool, pool_type, is_underlying)

        # check if get_dy works and if so, append quote to dynarray
        if quote > 0 and len(quotes) < MAX_QUOTES:
            quotes.append(
                Quote(
                    source_token_index=convert(i, uint256),
                    dest_token_index=convert(j, uint256),
                    is_underlying=is_underlying,
                    amount_out=quote,
                    pool=pool,
                    source_token_pool_balance=balances_i,
                    dest_token_pool_balance=balances_j,
                    pool_type=pool_type
                )
            )

    return quotes


@internal
@view
def _get_pool_type(pool: address, metaregistry: Metaregistry) -> uint8:
    
    # 0 for stableswap, 1 for cryptoswap, 2 for LLAMMA.

    success: bool = False
    response: Bytes[32] = b""

    # check if cryptoswap
    success, response = raw_call(
        pool,
        method_id("allowed_extra_profit()"),
        max_outsize=32,
        revert_on_failure=False,
        is_static_call=True
    )
    if success:
        return 1

    # check if llamma
    success, response = raw_call(
        pool,
        method_id("get_rate_mul()"),
        max_outsize=32,
        revert_on_failure=False,
        is_static_call=True
    )
    if success:
        return 2

    return 0


@internal
@view
def _get_pool_quote(
    i: int128,
    j: int128, 
    amount_in: uint256, 
    pool: address, 
    pool_type: uint8, 
    is_underlying: bool
) -> uint256:

    success: bool = False
    response: Bytes[32] = b""
    method_abi: Bytes[4] = b""

    # choose the right abi:
    if pool_type == 0 and is_underlying:
        method_abi = method_id(STABLESWAP_META_ABI)
    elif pool_type == 0 and not is_underlying:
        method_abi = method_id(STABLESWAP_ABI)
    else:
        method_abi = method_id(CRYPTOSWAP_ABI)

    success, response = raw_call(
        pool,
        concat(
            method_abi,
            convert(i, bytes32),
            convert(j, bytes32),
            convert(amount_in, bytes32),
        ),
        max_outsize=32,
        revert_on_failure=False,
        is_static_call=True
    )

    if success:
        return convert(response, uint256)

    return 0
