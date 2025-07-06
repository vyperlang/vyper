# pragma version >=0.4.2
# pragma optimize gas
# pragma evm-version shanghai
"""
@title CurveXChainLiquidityGauge
@license Copyright (c) Curve.Fi, 2020-2024 - all rights reserved
@author Curve.Fi
@notice Layer2//Cross-Chain Gauge
@custom:version 1.0.0
"""


from ethereum.ercs import IERC20

implements: IERC20


interface IERC20Extended:
    def symbol() -> String[32]: view

interface ERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes32: view

interface Factory:
    def owner() -> address: view
    def manager() -> address: view
    def voting_escrow() -> address: view
    def minted(_user: address, _gauge: address) -> uint256: view
    def crv() -> IERC20: view


event Deposit:
    provider: indexed(address)
    value: uint256

event Withdraw:
    provider: indexed(address)
    value: uint256

event UpdateLiquidityLimit:
    user: indexed(address)
    original_balance: uint256
    original_supply: uint256
    working_balance: uint256
    working_supply: uint256

event SetGaugeManager:
    _gauge_manager: address


event Transfer:
    _from: indexed(address)
    _to: indexed(address)
    _value: uint256

event Approval:
    _owner: indexed(address)
    _spender: indexed(address)
    _value: uint256


struct Reward:
    distributor: address
    period_finish: uint256
    rate: uint256
    last_update: uint256
    integral: uint256


MAX_REWARDS: constant(uint256) = 8
TOKENLESS_PRODUCTION: constant(uint256) = 40
WEEK: constant(uint256) = 604800

VERSION: constant(String[8]) = "1.0.0"

EIP712_TYPEHASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
EIP2612_TYPEHASH: constant(bytes32) = keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)")
ERC1271_MAGIC_VAL: constant(bytes32) = 0x1626ba7e00000000000000000000000000000000000000000000000000000000

voting_escrow: public(address)


# IERC20
balanceOf: public(HashMap[address, uint256])
totalSupply: public(uint256)
allowance: public(HashMap[address, HashMap[address, uint256]])

name: public(String[64])
symbol: public(String[40])

# ERC2612
DOMAIN_SEPARATOR: public(bytes32)
nonces: public(HashMap[address, uint256])

# Gauge
FACTORY: immutable(Factory)
manager: public(address)
lp_token: public(address)

is_killed: public(bool)

inflation_rate: public(HashMap[uint256, uint256])

# For tracking external rewards
reward_count: public(uint256)
reward_data: public(HashMap[address, Reward])
reward_remaining: public(HashMap[address, uint256])  # fixes bad precision

# claimant -> default reward receiver
rewards_receiver: public(HashMap[address, address])

# reward token -> claiming address -> integral
reward_integral_for: public(HashMap[address, HashMap[address, uint256]])

# user -> [uint128 claimable amount][uint128 claimed amount]
claim_data: HashMap[address, HashMap[address, uint256]]

working_balances: public(HashMap[address, uint256])
working_supply: public(uint256)

# 1e18 * ∫(rate(t) // totalSupply(t) dt) from (last_action) till checkpoint
integrate_inv_supply_of: public(HashMap[address, uint256])
integrate_checkpoint_of: public(HashMap[address, uint256])

# ∫(balance * rate(t) // totalSupply(t) dt) from 0 till checkpoint
# Units: rate * t = already number of coins per address to issue
integrate_fraction: public(HashMap[address, uint256])

# The goal is to be able to calculate ∫(rate * balance // totalSupply dt) from 0 till checkpoint
# All values are kept in units of being multiplied by 1e18
period: public(int128)

# array of reward tokens
reward_tokens: public(address[MAX_REWARDS])

period_timestamp: public(HashMap[int128, uint256])
# 1e18 * ∫(rate(t) // totalSupply(t) dt) from 0 till checkpoint
integrate_inv_supply: public(HashMap[int128, uint256])

# xchain specific
root_gauge: public(address)


@deploy
def __init__(_factory: Factory):
    self.lp_token = 0x000000000000000000000000000000000000dEaD

    FACTORY = _factory


@external
def initialize(_lp_token: address, _root: address, _manager: address):
    assert self.lp_token == empty(address)  # dev: already initialized

    self.lp_token = _lp_token
    self.root_gauge = _root
    self.manager = _manager

    self.voting_escrow = staticcall Factory(msg.sender).voting_escrow()

    symbol: String[32] = staticcall IERC20Extended(_lp_token).symbol()
    name: String[64] = concat("Curve.fi ", symbol, " Gauge Deposit")

    self.name = name
    self.symbol = concat(symbol, "-gauge")

    self.period_timestamp[0] = block.timestamp
    self.DOMAIN_SEPARATOR = keccak256(
        abi_encode(
            EIP712_TYPEHASH,
            keccak256(name),
            keccak256(VERSION),
            chain.id,
            self
        )
    )


# Internal Functions


@internal
def _checkpoint(_user: address):
    """
    @notice Checkpoint a user calculating their CRV entitlement
    @param _user User address
    """
    period: int128 = self.period
    period_time: uint256 = self.period_timestamp[period]
    integrate_inv_supply: uint256 = self.integrate_inv_supply[period]

    if block.timestamp > period_time:

        working_supply: uint256 = self.working_supply
        prev_week_time: uint256 = period_time
        week_time: uint256 = min((period_time + WEEK) // WEEK * WEEK, block.timestamp)

        for i: uint256 in range(256):
            dt: uint256 = week_time - prev_week_time

            if working_supply != 0:
                # we don't have to worry about crossing inflation epochs
                # and if we miss any weeks, those weeks inflation rates will be 0 for sure
                # but that means no one interacted with the gauge for that long
                integrate_inv_supply += self.inflation_rate[prev_week_time // WEEK] * 10 ** 18 * dt // working_supply

            if week_time == block.timestamp:
                break
            prev_week_time = week_time
            week_time = min(week_time + WEEK, block.timestamp)

    # check CRV balance and increase weekly inflation rate by delta for the rest of the week
    crv: IERC20 = staticcall FACTORY.crv()
    if crv != empty(IERC20):
        crv_balance: uint256 = staticcall crv.balanceOf(self)
        if crv_balance != 0:
            current_week: uint256 = block.timestamp // WEEK
            self.inflation_rate[current_week] += crv_balance // ((current_week + 1) * WEEK - block.timestamp)
            success: bool = extcall crv.transfer(FACTORY.address, crv_balance)
            assert success

    period += 1
    self.period = period
    self.period_timestamp[period] = block.timestamp
    self.integrate_inv_supply[period] = integrate_inv_supply

    working_balance: uint256 = self.working_balances[_user]
    self.integrate_fraction[_user] += working_balance * (integrate_inv_supply - self.integrate_inv_supply_of[_user]) // 10 ** 18
    self.integrate_inv_supply_of[_user] = integrate_inv_supply
    self.integrate_checkpoint_of[_user] = block.timestamp


@internal
def _checkpoint_rewards(_user: address, _total_supply: uint256, _claim: bool, _receiver: address):
    """
    @notice Claim pending rewards and checkpoint rewards for a user
    """

    user_balance: uint256 = 0
    receiver: address = _receiver
    if _user != empty(address):
        user_balance = self.balanceOf[_user]
        if _claim and _receiver == empty(address):
            # if receiver is not explicitly declared, check if a default receiver is set
            receiver = self.rewards_receiver[_user]
            if receiver == empty(address):
                # if no default receiver is set, direct claims to the user
                receiver = _user

    reward_count: uint256 = self.reward_count
    for i: uint256 in range(MAX_REWARDS):
        if i == reward_count:
            break
        token: address = self.reward_tokens[i]

        integral: uint256 = self.reward_data[token].integral
        period_finish: uint256 = self.reward_data[token].period_finish
        last_update: uint256 = min(block.timestamp, period_finish)
        duration: uint256 = last_update - self.reward_data[token].last_update

        if duration != 0 and _total_supply != 0:
            self.reward_data[token].last_update = last_update

            rate: uint256 = self.reward_data[token].rate
            excess: uint256 = self.reward_remaining[token] - (period_finish - last_update + duration) * rate
            integral_change: uint256 = (duration * rate + excess) * 10**18 // _total_supply
            integral += integral_change
            self.reward_data[token].integral = integral
            # There is still calculation error in user's claimable amount,
            # but it has 18-decimal precision through LP(_total_supply) – safe
            self.reward_remaining[token] -= integral_change * _total_supply // 10**18

        if _user != empty(address):
            integral_for: uint256 = self.reward_integral_for[token][_user]
            new_claimable: uint256 = 0

            if integral_for < integral:
                self.reward_integral_for[token][_user] = integral
                new_claimable = user_balance * (integral - integral_for) // 10**18

            claim_data: uint256 = self.claim_data[_user][token]
            total_claimable: uint256 = (claim_data >> 128) + new_claimable
            if total_claimable > 0:
                total_claimed: uint256 = claim_data % 2**128
                if _claim:
                    success: bool = extcall IERC20(token).transfer(receiver, total_claimable, default_return_value=True)
                    assert success
                    self.claim_data[_user][token] = total_claimed + total_claimable
                elif new_claimable > 0:
                    self.claim_data[_user][token] = total_claimed + (total_claimable << 128)


@internal
def _update_liquidity_limit(_user: address, _user_balance: uint256, _total_supply: uint256):
    """
    @notice Calculate working balances to apply amplification of CRV production.
    @dev https://resources.curve.fi//guides//boosting-your-crv-rewards#formula
    @param _user The user address
    @param _user_balance User's amount of liquidity (LP tokens)
    @param _total_supply Total amount of liquidity (LP tokens)
    """
    working_balance: uint256 = _user_balance * TOKENLESS_PRODUCTION // 100

    ve: address = self.voting_escrow
    if ve != empty(address):
        ve_ts: uint256 = staticcall IERC20(ve).totalSupply()
        if ve_ts != 0:
            working_balance += _total_supply * staticcall IERC20(ve).balanceOf(_user) // ve_ts * (100 - TOKENLESS_PRODUCTION) // 100
            working_balance = min(_user_balance, working_balance)

    old_working_balance: uint256 = self.working_balances[_user]
    self.working_balances[_user] = working_balance

    working_supply: uint256 = self.working_supply + working_balance - old_working_balance
    self.working_supply = working_supply

    log UpdateLiquidityLimit(user=_user, original_balance=_user_balance, original_supply=_total_supply, working_balance=working_balance, working_supply=working_supply)


@internal
def _transfer(_from: address, _to: address, _value: uint256):
    """
    @notice Transfer tokens as well as checkpoint users
    """
    self._checkpoint(_from)
    self._checkpoint(_to)

    if _value != 0:
        total_supply: uint256 = self.totalSupply
        is_rewards: bool = self.reward_count != 0
        if is_rewards:
            self._checkpoint_rewards(_from, total_supply, False, empty(address))
        new_balance: uint256 = self.balanceOf[_from] - _value
        self.balanceOf[_from] = new_balance
        self._update_liquidity_limit(_from, new_balance, total_supply)

        if is_rewards:
            self._checkpoint_rewards(_to, total_supply, False, empty(address))
        new_balance = self.balanceOf[_to] + _value
        self.balanceOf[_to] = new_balance
        self._update_liquidity_limit(_to, new_balance, total_supply)

    log Transfer(_from=_from, _to=_to, _value=_value)


# External User Facing Functions


@external
@nonreentrant
def deposit(_value: uint256, _addr: address = msg.sender, _claim_rewards: bool = False):
    """
    @notice Deposit `_value` LP tokens
    @dev Depositting also claims pending reward tokens
    @param _value Number of tokens to deposit
    @param _addr Address to deposit for
    """
    assert _addr != empty(address)  # dev: cannot deposit for zero address
    self._checkpoint(_addr)

    if _value != 0:
        is_rewards: bool = self.reward_count != 0
        total_supply: uint256 = self.totalSupply
        if is_rewards:
            self._checkpoint_rewards(_addr, total_supply, _claim_rewards, empty(address))

        total_supply += _value
        new_balance: uint256 = self.balanceOf[_addr] + _value
        self.balanceOf[_addr] = new_balance
        self.totalSupply = total_supply

        self._update_liquidity_limit(_addr, new_balance, total_supply)

        success: bool = extcall IERC20(self.lp_token).transferFrom(msg.sender, self, _value)
        assert success

        log Deposit(provider=_addr, value=_value)
        log Transfer(_from=empty(address), _to=_addr, _value=_value)


@external
@nonreentrant
def withdraw(_value: uint256, _claim_rewards: bool = False, _receiver: address = msg.sender):
    """
    @notice Withdraw `_value` LP tokens
    @dev Withdrawing also claims pending reward tokens
    @param _value Number of tokens to withdraw
    @param _claim_rewards Whether to claim rewards
    @param _receiver Receiver of withdrawn LP tokens
    """
    self._checkpoint(msg.sender)

    if _value != 0:
        is_rewards: bool = self.reward_count != 0
        total_supply: uint256 = self.totalSupply
        if is_rewards:
            self._checkpoint_rewards(msg.sender, total_supply, _claim_rewards, empty(address))

        total_supply -= _value
        new_balance: uint256 = self.balanceOf[msg.sender] - _value
        self.balanceOf[msg.sender] = new_balance
        self.totalSupply = total_supply

        self._update_liquidity_limit(msg.sender, new_balance, total_supply)

        success: bool = extcall IERC20(self.lp_token).transfer(_receiver, _value)
        assert success

    log Withdraw(provider=msg.sender, value=_value)
    log Transfer(_from=msg.sender, _to=empty(address), _value=_value)


@external
@nonreentrant
def claim_rewards(_addr: address = msg.sender, _receiver: address = empty(address)):
    """
    @notice Claim available reward tokens for `_addr`
    @param _addr Address to claim for
    @param _receiver Address to transfer rewards to - if set to
                     empty(address), uses the default reward receiver
                     for the caller
    """
    if _receiver != empty(address):
        assert _addr == msg.sender  # dev: cannot redirect when claiming for another user
    self._checkpoint_rewards(_addr, self.totalSupply, True, _receiver)


@external
@nonreentrant
def transferFrom(_from: address, _to :address, _value: uint256) -> bool:
    """
     @notice Transfer tokens from one address to another.
     @dev Transferring claims pending reward tokens for the sender and receiver
     @param _from address The address which you want to send tokens from
     @param _to address The address which you want to transfer to
     @param _value uint256 the amount of tokens to be transferred
    """
    _allowance: uint256 = self.allowance[_from][msg.sender]
    if _allowance != max_value(uint256):
        self.allowance[_from][msg.sender] = _allowance - _value

    self._transfer(_from, _to, _value)

    return True


@external
@nonreentrant
def transfer(_to: address, _value: uint256) -> bool:
    """
    @notice Transfer token for a specified address
    @dev Transferring claims pending reward tokens for the sender and receiver
    @param _to The address to transfer to.
    @param _value The amount to be transferred.
    """
    self._transfer(msg.sender, _to, _value)

    return True


@external
def approve(_spender : address, _value : uint256) -> bool:
    """
    @notice Approve the passed address to transfer the specified amount of
            tokens on behalf of msg.sender
    @dev Beware that changing an allowance via this method brings the risk
         that someone may use both the old and new allowance by unfortunate
         transaction ordering. This may be mitigated with the use of
         {incraseAllowance} and {decreaseAllowance}.
         https://github.com//ethereum//EIPs//issues//20#issuecomment-263524729
    @param _spender The address which will transfer the funds
    @param _value The amount of tokens that may be transferred
    @return bool success
    """
    self.allowance[msg.sender][_spender] = _value
    log Approval(_owner=msg.sender, _spender=_spender, _value=_value)

    return True


@external
def permit(
    _owner: address,
    _spender: address,
    _value: uint256,
    _deadline: uint256,
    _v: uint8,
    _r: bytes32,
    _s: bytes32
) -> bool:
    """
    @notice Approves spender by owner's signature to expend owner's tokens.
        See https://eips.ethereum.org//EIPS//eip-2612.
    @dev Inspired by https://github.com//yearn//yearn-vaults//blob//main//contracts//Vault.vy#L753-L793
    @dev Supports smart contract wallets which implement ERC1271
        https://eips.ethereum.org//EIPS//eip-1271
    @param _owner The address which is a source of funds and has signed the Permit.
    @param _spender The address which is allowed to spend the funds.
    @param _value The amount of tokens to be spent.
    @param _deadline The timestamp after which the Permit is no longer valid.
    @param _v The bytes[64] of the valid secp256k1 signature of permit by owner
    @param _r The bytes[0:32] of the valid secp256k1 signature of permit by owner
    @param _s The bytes[32:64] of the valid secp256k1 signature of permit by owner
    @return True, if transaction completes successfully
    """
    assert _owner != empty(address)  # dev: invalid owner
    assert block.timestamp <= _deadline  # dev: permit expired

    nonce: uint256 = self.nonces[_owner]
    digest: bytes32 = keccak256(
        concat(
            b"\x19\x01",
            self.DOMAIN_SEPARATOR,
            keccak256(
                abi_encode(
                    EIP2612_TYPEHASH, _owner, _spender, _value, nonce, _deadline
                )
            ),
        )
    )
    if _owner.is_contract:
        sig: Bytes[65] = concat(abi_encode(_r, _s), slice(convert(_v, bytes32), 31, 1))
        assert staticcall ERC1271(_owner).isValidSignature(digest, sig) == ERC1271_MAGIC_VAL  # dev: invalid signature
    else:
        assert ecrecover(digest, _v, _r, _s) == _owner  # dev: invalid signature

    self.allowance[_owner][_spender] = _value
    self.nonces[_owner] = unsafe_add(nonce, 1)

    log Approval(_owner=_owner, _spender=_spender, _value=_value)
    return True


@external
def increaseAllowance(_spender: address, _added_value: uint256) -> bool:
    """
    @notice Increase the allowance granted to `_spender` by the caller
    @dev This is alternative to {approve} that can be used as a mitigation for
         the potential race condition
    @param _spender The address which will transfer the funds
    @param _added_value The amount of to increase the allowance
    @return bool success
    """
    allowance: uint256 = self.allowance[msg.sender][_spender] + _added_value
    self.allowance[msg.sender][_spender] = allowance

    log Approval(_owner=msg.sender, _spender=_spender, _value=allowance)

    return True


@external
def decreaseAllowance(_spender: address, _subtracted_value: uint256) -> bool:
    """
    @notice Decrease the allowance granted to `_spender` by the caller
    @dev This is alternative to {approve} that can be used as a mitigation for
         the potential race condition
    @param _spender The address which will transfer the funds
    @param _subtracted_value The amount of to decrease the allowance
    @return bool success
    """
    allowance: uint256 = self.allowance[msg.sender][_spender] - _subtracted_value
    self.allowance[msg.sender][_spender] = allowance

    log Approval(_owner=msg.sender, _spender=_spender, _value=allowance)

    return True


@external
def user_checkpoint(addr: address) -> bool:
    """
    @notice Record a checkpoint for `addr`
    @param addr User address
    @return bool success
    """
    assert msg.sender in [addr, FACTORY.address]  # dev: unauthorized
    self._checkpoint(addr)
    self._update_liquidity_limit(addr, self.balanceOf[addr], self.totalSupply)
    return True


@external
def set_rewards_receiver(_receiver: address):
    """
    @notice Set the default reward receiver for the caller.
    @dev When set to empty(address), rewards are sent to the caller
    @param _receiver Receiver address for any rewards claimed via `claim_rewards`
    """
    self.rewards_receiver[msg.sender] = _receiver


# Administrative Functions


@external
def set_gauge_manager(_gauge_manager: address):
    """
    @notice Change the gauge manager for a gauge
    @dev The manager of this contract, or the ownership admin can outright modify gauge
        managership. A gauge manager can also transfer managership to a new manager via this
        method, but only for the gauge which they are the manager of.
    @param _gauge_manager The account to set as the new manager of the gauge.
    """
    assert msg.sender in [self.manager, staticcall FACTORY.owner()]  # dev: only manager or factory admin

    self.manager = _gauge_manager
    log SetGaugeManager(_gauge_manager=_gauge_manager)


@external
def set_manager(_gauge_manager: address):
    """
    @notice Change the gauge manager for a gauge
    @dev Copy of `set_gauge_manager` for back-compatability
    @dev The manager of this contract, or the ownership admin can outright modify gauge
        managership. A gauge manager can also transfer managership to a new manager via this
        method, but only for the gauge which they are the manager of.
    @param _gauge_manager The account to set as the new manager of the gauge.
    """
    assert msg.sender in [self.manager, staticcall FACTORY.owner()]  # dev: only manager or factory admin

    self.manager = _gauge_manager
    log SetGaugeManager(_gauge_manager=_gauge_manager)


@external
@nonreentrant
def deposit_reward_token(_reward_token: address, _amount: uint256, _epoch: uint256 = WEEK):
    """
    @notice Deposit a reward token for distribution
    @param _reward_token The reward token being deposited
    @param _amount The amount of `_reward_token` being deposited
    @param _epoch The duration the rewards are distributed across. Between 3 days and a year, week by default
    """
    assert msg.sender == self.reward_data[_reward_token].distributor
    assert 3 * WEEK // 7 <= _epoch and _epoch <= WEEK * 4 * 12, "Epoch duration"

    self._checkpoint_rewards(empty(address), self.totalSupply, False, empty(address))

    # transferFrom reward token and use transferred amount henceforth:
    amount_received: uint256 = staticcall IERC20(_reward_token).balanceOf(self)
    success: bool = extcall IERC20(_reward_token).transferFrom(
        msg.sender,
        self,
        _amount,
        default_return_value=True
    )
    assert success
    amount_received = staticcall IERC20(_reward_token).balanceOf(self) - amount_received

    total_amount: uint256 = amount_received + self.reward_remaining[_reward_token]
    self.reward_data[_reward_token].rate = total_amount // _epoch
    self.reward_remaining[_reward_token] = total_amount

    self.reward_data[_reward_token].last_update = block.timestamp
    self.reward_data[_reward_token].period_finish = block.timestamp + _epoch


@external
def recover_remaining(_reward_token: address):
    """
    @notice Recover reward token remaining after calculation errors. Helpful for small decimal tokens.
    Remaining tokens will be claimable in favor of distributor. Callable by anyone after reward distribution finished.
    @param _reward_token The reward token being recovered
    """
    self._checkpoint_rewards(empty(address), self.totalSupply, False, empty(address))

    period_finish: uint256 = self.reward_data[_reward_token].period_finish
    assert period_finish < block.timestamp
    assert self.reward_data[_reward_token].last_update >= period_finish

    success: bool = extcall IERC20(_reward_token).transfer(self.reward_data[_reward_token].distributor,
        self.reward_remaining[_reward_token], default_return_value=True)
    assert success
    self.reward_remaining[_reward_token] = 0


@external
def add_reward(_reward_token: address, _distributor: address):
    """
    @notice Add additional rewards to be distributed to stakers
    @param _reward_token The token to add as an additional reward
    @param _distributor Address permitted to fund this contract with the reward token
    """
    assert msg.sender in [self.manager, staticcall FACTORY.owner()]  # dev: only manager or factory admin
    crv_token: IERC20 = staticcall FACTORY.crv()
    assert _reward_token != crv_token.address  # dev: can not distinguish CRV reward from CRV emission
    assert _distributor != empty(address)  # dev: distributor cannot be zero address

    reward_count: uint256 = self.reward_count
    assert reward_count < MAX_REWARDS
    assert self.reward_data[_reward_token].distributor == empty(address)

    self.reward_data[_reward_token].distributor = _distributor
    self.reward_tokens[reward_count] = _reward_token
    self.reward_count = reward_count + 1


@external
def set_reward_distributor(_reward_token: address, _distributor: address):
    """
    @notice Reassign the reward distributor for a reward token
    @param _reward_token The reward token to reassign distribution rights to
    @param _distributor The address of the new distributor
    """
    current_distributor: address = self.reward_data[_reward_token].distributor

    assert msg.sender in [current_distributor, staticcall FACTORY.owner(), self.manager]
    assert current_distributor != empty(address)
    assert _distributor != empty(address)

    self.reward_data[_reward_token].distributor = _distributor


@external
def set_killed(_is_killed: bool):
    """
    @notice Set the killed status for this contract
    @dev Nothing happens, just stop emissions and that's it
    @param _is_killed Killed status to set
    """
    assert msg.sender == staticcall FACTORY.owner()  # dev: only owner

    self.is_killed = _is_killed


@external
def set_root_gauge(_root: address):
    """
    @notice Set Root contract in case something went wrong (e.g. between implementation updates)
    @param _root Root gauge to set
    """
    assert msg.sender in [staticcall FACTORY.owner(), staticcall FACTORY.manager()]
    assert _root != empty(address)

    self.root_gauge = _root


@external
def update_voting_escrow():
    """
    @notice Update the voting escrow contract in storage
    """
    self.voting_escrow = staticcall FACTORY.voting_escrow()


# View Methods


@view
@external
def claimed_reward(_addr: address, _token: address) -> uint256:
    """
    @notice Get the number of already-claimed reward tokens for a user
    @param _addr Account to get reward amount for
    @param _token Token to get reward amount for
    @return uint256 Total amount of `_token` already claimed by `_addr`
    """
    return self.claim_data[_addr][_token] % 2**128


@view
@external
def claimable_reward(_user: address, _reward_token: address) -> uint256:
    """
    @notice Get the number of claimable reward tokens for a user
    @param _user Account to get reward amount for
    @param _reward_token Token to get reward amount for
    @return uint256 Claimable reward token amount
    """
    integral: uint256 = self.reward_data[_reward_token].integral
    total_supply: uint256 = self.totalSupply
    if total_supply != 0:
        last_update: uint256 = min(block.timestamp, self.reward_data[_reward_token].period_finish)
        duration: uint256 = last_update - self.reward_data[_reward_token].last_update
        integral += (duration * self.reward_data[_reward_token].rate * 10**18 // total_supply)

    integral_for: uint256 = self.reward_integral_for[_reward_token][_user]
    new_claimable: uint256 = self.balanceOf[_user] * (integral - integral_for) // 10**18

    return (self.claim_data[_user][_reward_token] >> 128) + new_claimable


@external
def claimable_tokens(addr: address) -> uint256:
    """
    @notice Get the number of claimable tokens per user
    @dev This function should be manually changed to "view" in the ABI
    @return uint256 number of claimable tokens per user
    """
    self._checkpoint(addr)
    return self.integrate_fraction[addr] - staticcall FACTORY.minted(addr, self)


@view
@external
def integrate_checkpoint() -> uint256:
    """
    @notice Get the timestamp of the last checkpoint
    """
    return self.period_timestamp[self.period]


@view
@external
def decimals() -> uint256:
    """
    @notice Get the number of decimals for this token
    @dev Implemented as a view method to reduce gas costs
    @return uint256 decimal places
    """
    return 18


@view
@external
def version() -> String[8]:
    """
    @notice Get the version of this gauge contract
    """
    return VERSION


@view
@external
def factory() -> Factory:
    """
    @notice Get factory of this gauge
    """
    return FACTORY
