# pragma version >=0.4.2
"""
@title CurveRateProvider
@custom:version 1.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Provides quotes for coin pairs, iff coin pair is in a Curve AMM that the Metaregistry recognises.
"""

version: public(constant(String[8])) = "1.0.0"

MAX_COINS: constant(uint256) = 8
MAX_QUOTES: constant(uint256) = 100

struct Quote:
    source_token_index: uint256
    dest_token_index: uint256
    is_underlying: bool
    amount_out: uint256
    pool: address
    pool_balances: DynArray[uint256, MAX_COINS]
    pool_type: uint8  # 0 for stableswap, 1 for cryptoswap, 2 for LLAMMA.


# Interfaces

interface AddressProvider:
    def get_address(id: uint256) -> address: view

interface Metaregistry:
    def find_pools_for_coins(source_coin: address, destination_coin: address) -> DynArray[address, 1000]: view
    def get_coin_indices(_pool: address, _from: address, _to: address) -> (int128, int128, bool): view
    def get_underlying_balances(_pool: address) -> uint256[MAX_COINS]: view
    def get_n_underlying_coins(_pool: address) -> uint256: view
    def get_underlying_decimals(_pool: address) -> uint256[MAX_COINS]: view


ADDRESS_PROVIDER: public(immutable(AddressProvider))
METAREGISTRY_ID: constant(uint256) = 7
STABLESWAP_META_ABI: constant(String[64]) = "get_dy_underlying(int128,int128,uint256)"
STABLESWA_ABI: constant(String[64]) = "get_dy(int128,int128,uint256)"
CRYPTOSWAP_ABI: constant(String[64]) = "get_dy(uint256,uint256,uint256)"

@deploy
def __init__(address_provider: address):
    ADDRESS_PROVIDER = AddressProvider(address_provider)

# Quote View method

@external
@view
def get_quotes(source_token: address, destination_token: address, amount_in: uint256) -> DynArray[Quote, MAX_QUOTES]:

    quotes: DynArray[Quote, MAX_QUOTES] = []
    metaregistry: Metaregistry = Metaregistry(staticcall ADDRESS_PROVIDER.get_address(METAREGISTRY_ID))
    pools: DynArray[address, 1000] = staticcall metaregistry.find_pools_for_coins(source_token, destination_token)

    if len(pools) == 0:
        return quotes

    # get  pool types for each pool
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

        # if pool is too small, dont post call and skip pool:
        if balances[i] <= amount_in:
            continue

        # convert to Dynamic Arrays:
        dyn_balances: DynArray[uint256, MAX_COINS] = []
        for bal: uint256 in balances:
            if bal > 0:
                dyn_balances.append(bal)

        # do a get_dy call and only save quote if call does not bork; use correct abi (in128 vs uint256)
        success: bool = False
        response: Bytes[32] = b""
        if pool_type == 0 and is_underlying:
            success, response = raw_call(
            pool,
            concat(
                method_id(STABLESWAP_META_ABI),
                convert(i, bytes32),
                convert(j, bytes32),
                convert(amount_in, bytes32),
            ),
            max_outsize=32,
            revert_on_failure=False,
            is_static_call=True
        )
        elif pool_type == 0 and not is_underlying:
            success, response = raw_call(
            pool,
            concat(
                method_id(STABLESWA_ABI),
                convert(i, bytes32),
                convert(j, bytes32),
                convert(amount_in, bytes32),
            ),
            max_outsize=32,
            revert_on_failure=False,
            is_static_call=True
        )
        else:
            success, response = raw_call(
            pool,
            concat(
                method_id(CRYPTOSWAP_ABI),
                convert(i, bytes32),
                convert(j, bytes32),
                convert(amount_in, bytes32),
            ),
            max_outsize=32,
            revert_on_failure=False,
            is_static_call=True
        )

        # check if get_dy works and if so, append quote to dynarray
        if success:
            quotes.append(
                Quote(
                    source_token_index=convert(i, uint256),
                    dest_token_index=convert(j, uint256),
                    is_underlying=is_underlying,
                    amount_out=convert(response, uint256),
                    pool=pool,
                    pool_balances=dyn_balances,
                    pool_type=pool_type
                )
            )

    return quotes

# Internal methods

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
