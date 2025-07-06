# pragma version >=0.4.2
# pragma evm-version paris

"""
@title CurveDeposit&StakeZap
@custom:version 1.0.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice A zap to add liquidity to pool and deposit into gauge in one transaction
"""

version: public(constant(String[8])) = "1.0.0"


# External Contracts
from ethereum.ercs import IERC20

interface Pool2:
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256): nonpayable

interface Pool3:
    def add_liquidity(amounts: uint256[3], min_mint_amount: uint256): nonpayable

interface StableSwap:
    def add_liquidity(_amounts: DynArray[uint256, MAX_COINS], _min_mint_amount: uint256): nonpayable

interface MetaZap:
    def add_liquidity(pool: address, _amounts: DynArray[uint256, MAX_COINS], _min_mint_amount: uint256): nonpayable

interface Gauge:
    def deposit(lp_token_amount: uint256, addr: address): nonpayable


MAX_COINS: constant(uint256) = 9


@external
@nonreentrant
def deposit_and_stake(
        deposit: address,
        lp_token: address,
        gauge: address,
        n_coins: uint256,
        coins: DynArray[address, MAX_COINS],
        amounts: DynArray[uint256, MAX_COINS],
        min_mint_amount: uint256,
        use_dynarray: bool,
        pool: address = empty(address),
) -> uint256:
    """
    @notice Deposit coins into pool and stake obtained LP tokens into gauge.
            Zap address should be passed to `deposit` arg in case of meta-pool deposit with underlying coins.
    @param deposit Zap address for meta-pool deposit with underlying coins, pool address for other cases
    @param lp_token The address of LP token
    @param gauge The address of gauge
    @param n_coins The number of tokens (underlying or wrapped for meta-pools)
    @param coins List of addresses of coins (underlying or wrapped for meta-pools)
    @param amounts List of amounts of coins to deposit (underlying or wrapped for meta-pools)
    @param min_mint_amount Minimum amount of LP tokens to mint from the deposit
    @param use_dynarray True - plain stable, meta stable with underlying coins
                        False - twocrypto, tricrypto, meta stable with wrapped coins
    @param pool The address of meta-pool in case of deposit with underlying coins
    @return Amount of LP tokens staked into gauge
    """
    assert n_coins >= 2, 'n_coins must be >=2'
    assert n_coins <= MAX_COINS, 'n_coins must be <=MAX_COINS'

    # Ensure allowance for swap or zap
    for i: uint256 in range(n_coins, bound=MAX_COINS):

        if amounts[i] == 0 or staticcall IERC20(coins[i]).allowance(self, deposit) > 0:
            continue

        staticcall IERC20(coins[i]).approve(deposit, max_value(uint256), default_return_value=True)

    # Ensure allowance for gauge
    if staticcall IERC20(lp_token).allowance(self, gauge) == 0:
        staticcall IERC20(lp_token).approve(gauge, max_value(uint256))

    # Transfer coins from owner
    for i: uint256 in range(n_coins, bound=MAX_COINS):

        if amounts[i] > 0:
            assert staticcall IERC20(coins[i]).transferFrom(msg.sender, self, amounts[i], default_return_value=True)

    # Deposit into pool
    if pool != empty(address):  # meta-pool deposit with underlying coins, deposit is zap here
        MetaZap(deposit).add_liquidity(pool, amounts, min_mint_amount)
    elif use_dynarray:  # plain stable pool
        StableSwap(deposit).add_liquidity(amounts, min_mint_amount)
    else:
        if n_coins == 2:  # twocrypto or meta-pool deposit with wrapped coins
            Pool2(deposit).add_liquidity([amounts[0], amounts[1]], min_mint_amount)
        elif n_coins == 3:  # tricrypto
            Pool3(deposit).add_liquidity([amounts[0], amounts[1], amounts[2]], min_mint_amount)
        else:
            raise "Wrong arguments"

    # Stake into gauge
    lp_token_amount: uint256 = staticcall IERC20(lp_token).balanceOf(self)
    assert lp_token_amount > 0 # dev: swap-token mismatch

    Gauge(gauge).deposit(lp_token_amount, msg.sender)

    return lp_token_amount
