# pragma version >=0.4.2

"""
@title CurveRouter
@custom:version 1.1.0
@author Curve.Fi
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@notice Performs up to 5 swaps in a single transaction
        Can do estimations with get_dy and get_dx
"""

version: public(constant(String[8])) = "1.1.0"  # ng pools


from ethereum.ercs import IERC20

interface StableNgPool:
    def get_dy(i: int128, j: int128, in_amount: uint256) -> uint256: view
    def get_dx(i: int128, j: int128, out_amount: uint256) -> uint256: view
    def exchange(i: int128, j: int128, dx: uint256, min_dy: uint256): nonpayable
    def calc_token_amount(_amounts: DynArray[uint256, 8], _is_deposit: bool) -> uint256: view
    def add_liquidity(_amounts: DynArray[uint256, 8], _min_mint_amount: uint256) -> uint256: nonpayable
    def calc_withdraw_one_coin(token_amount: uint256, i: int128) -> uint256: view
    def remove_liquidity_one_coin(token_amount: uint256, i: int128, min_amount: uint256): nonpayable

interface StableNgMetaPool:
    def get_dy_underlying(i: int128, j: int128, amount: uint256) -> uint256: view
    def get_dx_underlying(i: int128, j: int128, amount: uint256) -> uint256: view
    def exchange_underlying(i: int128, j: int128, dx: uint256, min_dy: uint256): nonpayable

interface CryptoNgPool:
    def get_dy(i: uint256, j: uint256, in_amount: uint256) -> uint256: view
    def get_dx(i: uint256, j: uint256, out_amount: uint256) -> uint256: view
    def exchange(i: uint256, j: uint256, dx: uint256, min_dy: uint256): nonpayable
    def calc_withdraw_one_coin(token_amount: uint256, i: uint256) -> uint256: view
    def remove_liquidity_one_coin(token_amount: uint256, i: uint256, min_amount: uint256): nonpayable

interface TwoCryptoNgPool:
    def calc_token_amount(amounts: uint256[2], is_deposit: bool) -> uint256: view
    def add_liquidity(amounts: uint256[2], min_mint_amount: uint256) -> uint256: nonpayable

interface TriCryptoNgPool:
    def calc_token_amount(amounts: uint256[3], is_deposit: bool) -> uint256: view
    def add_liquidity(amounts: uint256[3], min_mint_amount: uint256) -> uint256: nonpayable

interface WETH:
    def deposit(): payable
    def withdraw(_amount: uint256): nonpayable


event Exchange:
    sender: indexed(address)
    receiver: indexed(address)
    route: address[11]
    swap_params: uint256[4][5]
    in_amount: uint256
    out_amount: uint256


ETH_ADDRESS: constant(address) = 0xEeeeeEeeeEeEeeEeEeEeeEEEeeeeEeeeeeeeEEeE
WETH_ADDRESS: immutable(address)

is_approved: HashMap[address, HashMap[address, bool]]


@external
@payable
def __default__():
    pass


@deploy
def __init__( _weth: address):
    WETH_ADDRESS = _weth


@external
@payable
@nonreentrant
def exchange(
    _route: address[11],
    _swap_params: uint256[4][5],
    _amount: uint256,
    _min_dy: uint256,
    _receiver: address=msg.sender
) -> uint256:
    """
    @notice Performs up to 5 swaps in a single transaction.
    @dev Routing and swap params must be determined off-chain. This
         functionality is designed for gas efficiency over ease-of-use.
    @param _route Array of [initial token, pool, token, pool, token, ...]
                  The array is iterated until a pool address of 0x00, then the last
                  given token is transferred to `_receiver`
    @param _swap_params Multidimensional array of [i, j, swap type, pool_type] where
                        i is the index of input token
                        j is the index of output token

                        The swap_type should be:
                        1. for `exchange`,
                        2. for `exchange_underlying` (stable-ng metapools),
                        3. -- legacy --
                        4. for coin -> LP token "exchange" (actually `add_liquidity`),
                        5. -- legacy --
                        6. for LP token -> coin "exchange" (actually `remove_liquidity_one_coin`)
                        7. -- legacy --
                        8. for ETH <-> WETH

                        pool_type: 10 - stable-ng, 20 - twocrypto-ng, 30 - tricrypto-ng, 4 - llamma

    @param _amount The amount of input token (`_route[0]`) to be sent.
    @param _min_dy The minimum amount received after the final swap.
    @param _receiver Address to transfer the final output token to.
    @return Received amount of the final output token.
    """
    input_token: address = _route[0]
    output_token: address = empty(address)
    amount: uint256 = _amount

    # validate // transfer initial token
    if input_token == ETH_ADDRESS:
        assert msg.value == amount
    else:
        assert msg.value == 0
        assert extcall IERC20(input_token).transferFrom(msg.sender, self, amount, default_return_value=True)

    for i: uint256 in range(5):
        # 5 rounds of iteration to perform up to 5 swaps
        swap: address = _route[i * 2 + 1]
        output_token = _route[(i + 1) * 2]
        params: uint256[4] = _swap_params[i]  # i, j, swap_type, pool_type

        # store the initial balance of the output_token
        output_token_initial_balance: uint256 = self.balance
        if output_token != ETH_ADDRESS:
            output_token_initial_balance = staticcall IERC20(output_token).balanceOf(self)

        if not self.is_approved[input_token][swap]:
            assert extcall IERC20(input_token).approve(swap, max_value(uint256), default_return_value=True, skip_contract_check=True)
            self.is_approved[input_token][swap] = True

        # perform the swap according to the swap type
        if params[2] == 1:
            if params[3] == 10:  # stable-ng
                extcall StableNgPool(swap).exchange(convert(params[0], int128), convert(params[1], int128), amount, 0)
            else:  # twocrypto-ng, tricrypto-ng, llamma
                extcall CryptoNgPool(swap).exchange(params[0], params[1], amount, 0)
        elif params[2] == 2:  # stable-ng metapools
            extcall StableNgMetaPool(swap).exchange_underlying(convert(params[0], int128), convert(params[1], int128), amount, 0)
        elif params[2] == 4:
            if params[3] == 10:  # stable-ng
                amounts: DynArray[uint256, 8] = [0, 0, 0, 0, 0, 0, 0, 0]
                amounts[params[0]] = amount
                extcall StableNgPool(swap).add_liquidity(amounts, 0)
            elif params[3] == 20:  # twocrypto-ng
                amounts: uint256[2] = [0, 0]
                amounts[params[0]] = amount
                extcall TwoCryptoNgPool(swap).add_liquidity(amounts, 0)
            elif params[3] == 30:  # tricrypto-ng
                amounts: uint256[3] = [0, 0, 0]
                amounts[params[0]] = amount
                extcall TriCryptoNgPool(swap).add_liquidity(amounts, 0)
        elif params[2] == 6:
            if params[3] == 10:  # stable-ng
                extcall StableNgPool(swap).remove_liquidity_one_coin(amount, convert(params[1], int128), 0)
            else:  # twocrypto-ng, tricrypto-ng
                extcall CryptoNgPool(swap).remove_liquidity_one_coin(amount, params[1], 0)
        elif params[2] == 8:
            if input_token == ETH_ADDRESS and output_token == WETH_ADDRESS:
                extcall WETH(swap).deposit(value=amount)
            elif input_token == WETH_ADDRESS and output_token == ETH_ADDRESS:
                extcall WETH(swap).withdraw(amount)
            else:
                raise "Swap type 8 is only for ETH <-> WETH"
        else:
            raise "Bad swap type"

        # update the amount received
        if output_token == ETH_ADDRESS:
            amount = self.balance
        else:
            amount = staticcall IERC20(output_token).balanceOf(self)

        # sanity check, if the routing data is incorrect we will have a 0 balance change and that is bad
        assert amount - output_token_initial_balance != 0, "Received nothing"

        # check if this was the last swap
        if i == 4 or _route[i * 2 + 3] == empty(address):
            break
        # if there is another swap, the output token becomes the input for the next round
        input_token = output_token

    amount -= 1  # Change non-zero -> non-zero costs less gas than zero -> non-zero
    assert amount >= _min_dy, "Slippage"

    # transfer the final token to the receiver
    if output_token == ETH_ADDRESS:
        raw_call(_receiver, b"", value=amount)
    else:
        assert extcall IERC20(output_token).transfer(_receiver, amount, default_return_value=True)

    log Exchange(sender=msg.sender, receiver=_receiver, route=_route, swap_params=_swap_params, in_amount=_amount, out_amount=amount)

    return amount


@view
@external
def get_dy(
    _route: address[11],
    _swap_params: uint256[4][5],
    _amount: uint256,
) -> uint256:
    """
    @notice Get amount of the final output token received in an exchange
    @dev Routing and swap params must be determined off-chain. This
         functionality is designed for gas efficiency over ease-of-use.
    @param _route Array of [initial token, pool, token, pool, token, ...]
                  The array is iterated until a pool address of 0x00, then the last
                  given token is transferred to `_receiver`
    @param _swap_params Multidimensional array of [i, j, swap type, pool_type] where
                        i is the index of input token
                        j is the index of output token

                        The swap_type should be:
                        1. for `exchange`,
                        2. for `exchange_underlying` (stable-ng metapools),
                        3. -- legacy --
                        4. for coin -> LP token "exchange" (actually `add_liquidity`),
                        5. -- legacy --
                        6. for LP token -> coin "exchange" (actually `remove_liquidity_one_coin`)
                        7. -- legacy --
                        8. for ETH <-> WETH

                        pool_type: 10 - stable-ng, 20 - twocrypto-ng, 30 - tricrypto-ng, 4 - llamma

    @param _amount The amount of input token (`_route[0]`) to be sent.
    @return Expected amount of the final output token.
    """
    amount: uint256 = _amount

    for i: uint256 in range(5):
        # 5 rounds of iteration to perform up to 5 swaps
        swap: address = _route[i * 2 + 1]
        params: uint256[4] = _swap_params[i]  # i, j, swap_type, pool_type

        # Calc output amount according to the swap type
        if params[2] == 1:
            if params[3] == 10:  # stable_ng
                amount = staticcall StableNgPool(swap).get_dy(convert(params[0], int128), convert(params[1], int128), amount)
            else:  # twocrypto-ng, tricrypto-ng, llamma
                amount = staticcall CryptoNgPool(swap).get_dy(params[0], params[1], amount)
        elif params[2] == 2:  # stable-ng metapools
                amount = staticcall StableNgMetaPool(swap).get_dy_underlying(convert(params[0], int128), convert(params[1], int128), amount)
        elif params[2] == 4:
            if params[3] == 10:  # stable-ng
                amounts: DynArray[uint256, 8] = [0, 0, 0, 0, 0, 0, 0, 0]
                amounts[params[0]] = amount
                amount = staticcall StableNgPool(swap).calc_token_amount(amounts, True)
            elif params[3] == 20:  # twocrypto-ng
                amounts: uint256[2] = [0, 0]
                amounts[params[0]] = amount
                amount = staticcall TwoCryptoNgPool(swap).calc_token_amount(amounts, True)
            elif params[3] == 30:  # tricrypto-ng
                amounts: uint256[3] = [0, 0, 0]
                amounts[params[0]] = amount
                amount = staticcall TriCryptoNgPool(swap).calc_token_amount(amounts, True)
        elif params[2] == 6:
            if params[3] == 10:  # stable-ng
                amount = staticcall StableNgPool(swap).calc_withdraw_one_coin(amount, convert(params[1], int128))
            else:  # twocrypto-ng, tricrypto-ng
                amount = staticcall CryptoNgPool(swap).calc_withdraw_one_coin(amount, params[1])
        elif params[2] == 8:
            # ETH <--> WETH rate is 1:1
            pass
        else:
            raise "Bad swap type"

        # check if this was the last swap
        if i == 4 or _route[i * 2 + 3] == empty(address):
            break

    return amount - 1


@view
@external
def get_dx(
    _route: address[11],
    _swap_params: uint256[4][5],
    _out_amount: uint256,
    _base_pools: address[5]=empty(address[5]),
) -> uint256:
    """
    @notice Calculate the input amount required to receive the desired output amount
    @dev Routing and swap params must be determined off-chain. This
         functionality is designed for gas efficiency over ease-of-use.
    @param _route Array of [initial token, pool, token, pool, token, ...]
                  The array is iterated until a pool address of 0x00, then the last
                  given token is transferred to `_receiver`
    @param _swap_params Multidimensional array of [i, j, swap type, pool_type] where
                        i is the index of input token
                        j is the index of output token

                        The swap_type should be:
                        1. for `exchange`,
                        2. for `exchange_underlying` (stable-ng metapools),
                        3. -- legacy --
                        4. for coin -> LP token "exchange" (actually `add_liquidity`),
                        5. -- legacy --
                        6. for LP token -> coin "exchange" (actually `remove_liquidity_one_coin`)
                        7. -- legacy --
                        8. for ETH <-> WETH

                        pool_type: 10 - stable-ng, 20 - twocrypto-ng, 30 - tricrypto-ng, 4 - llamma

    @param _out_amount The desired amount of output coin to receive.
    @param _base_pools Array of base pools (for meta pools).
    @return Required amount of input token to send.
    """
    amount: uint256 = _out_amount

    for _i: uint256 in range(5):
        # 5 rounds of iteration to perform up to 5 swaps
        i: uint256 = 4 - _i
        swap: address = _route[i * 2 + 1]
        if swap == empty(address):
            continue
        base_pool: address = _base_pools[i]
        params: uint256[4] = _swap_params[i]  # i, j, swap_type, pool_type

        # Calc a required input amount according to the swap type
        if params[2] == 1:
            if params[3] == 10:  # stable-ng
                amount = staticcall StableNgPool(swap).get_dx(convert(params[0], int128), convert(params[1], int128), amount)
            else:  # twocrypto-ng, tricrypto-ng, llamma
                amount = staticcall CryptoNgPool(swap).get_dx(params[0], params[1], amount)
        elif params[2] == 2:  # stable-ng metapool
            _n: int128 = convert(params[0], int128)
            _k: int128 = convert(params[1], int128)
            if _n > 0 and _k > 0:
                amount = staticcall StableNgPool(base_pool).get_dx(_n - 1, _k - 1, amount)
            else:
                amount = staticcall StableNgMetaPool(swap).get_dx_underlying(_n, _k, amount)
        elif params[2] == 4:
            # This is not correct. Should be something like calc_add_one_coin. But tests say that it's precise enough.
            if params[3] == 10:  # stable_ng
                amount = staticcall StableNgPool(swap).calc_withdraw_one_coin(amount, convert(params[0], int128))
            else:  # twocrypto-ng, tricrypto-ng
                amount = staticcall CryptoNgPool(swap).calc_withdraw_one_coin(amount, params[0])
        elif params[2] == 6:
            if params[3] == 10:  # stable-ng
                amounts: DynArray[uint256, 8] = [0, 0, 0, 0, 0, 0, 0, 0]
                amounts[params[1]] = amount
                amount = staticcall StableNgPool(swap).calc_token_amount(amounts, False)
            elif params[3] == 20:  # twocrypto-ng
                amounts: uint256[2] = [0, 0]
                amounts[params[1]] = amount
                amount = staticcall TwoCryptoNgPool(swap).calc_token_amount(amounts, False)
            elif params[3] == 30:  # tricrypto-ng
                amounts: uint256[3] = [0, 0, 0]
                amounts[params[1]] = amount
                amount = staticcall TriCryptoNgPool(swap).calc_token_amount(amounts, False)
        elif params[2] == 8:
            # ETH <--> WETH rate is 1:1
            pass
        else:
            raise "Bad swap type"

    return amount
