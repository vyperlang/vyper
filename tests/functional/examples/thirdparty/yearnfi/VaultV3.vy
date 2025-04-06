
from ethereum.ercs import IERC20
from ethereum.ercs import IERC20Detailed

# INTERFACES #
interface IStrategy:
    def asset() -> address: view
    def balanceOf(owner: address) -> uint256: view
    def maxDeposit(receiver: address) -> uint256: view
    def maxWithdraw(owner: address) -> uint256: view
    def withdraw(amount: uint256, receiver: address, owner: address) -> uint256: nonpayable
    def deposit(assets: uint256, receiver: address) -> uint256: nonpayable
    def totalAssets() -> (uint256): view
    def convertToAssets(shares: uint256) -> (uint256): view
    def convertToShares(assets: uint256) -> (uint256): view

interface IAccountant:
    def report(strategy: address, gain: uint256, loss: uint256) -> (uint256, uint256): nonpayable

interface IQueueManager:
    def withdraw_queue(vault: address) -> (DynArray[address, 10]): nonpayable
    def new_strategy(strategy: address): nonpayable
    def remove_strategy(strategy: address): nonpayable

interface IFactory:
    def protocol_fee_config() -> (uint16, uint32, address): view

# EVENTS #
# ERC4626 EVENTS
event Deposit:
    sender: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256

event Withdraw:
    sender: indexed(address)
    receiver: indexed(address)
    owner: indexed(address)
    assets: uint256
    shares: uint256

# ERC20 EVENTS
event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

# STRATEGY EVENTS
event StrategyChanged:
    strategy: indexed(address)
    change_type: indexed(StrategyChangeType)
    
event StrategyReported:
    strategy: indexed(address)
    gain: uint256
    loss: uint256
    current_debt: uint256
    protocol_fees: uint256
    total_fees: uint256
    total_refunds: uint256

# DEBT MANAGEMENT EVENTS
event DebtUpdated:
    strategy: indexed(address)
    current_debt: uint256
    new_debt: uint256

# ROLE UPDATES
event RoleSet:
    account: indexed(address)
    role: indexed(Roles)

event RoleStatusChanged:
    role: indexed(Roles)
    status: indexed(RoleStatusChange)

# STORAGE MANAGEMENT EVENTS
event UpdateRoleManager:
    role_manager: indexed(address)

event UpdateAccountant:
    accountant: indexed(address)

event UpdateQueueManager:
    queue_manager: indexed(address)

event UpdatedMaxDebtForStrategy:
    sender: indexed(address)
    strategy: indexed(address)
    new_debt: uint256

event UpdateDepositLimit:
    deposit_limit: uint256

event UpdateMinimumTotalIdle:
    minimum_total_idle: uint256

event UpdateProfitMaxUnlockTime:
    profit_max_unlock_time: uint256

event Shutdown:
    pass

event Sweep:
    token: indexed(address)
    amount: uint256

# STRUCTS #
struct StrategyParams:
    activation: uint256
    last_report: uint256
    current_debt: uint256
    max_debt: uint256

# CONSTANTS #
MAX_BPS: constant(uint256) = 10_000
MAX_BPS_EXTENDED: constant(uint256) = 1_000_000_000_000
PROTOCOL_FEE_ASSESSMENT_PERIOD: constant(uint256) = 24 * 3600 # assess once a day
API_VERSION: constant(String[28]) = "3.1.0"

# ENUMS #
# Each permissioned function has its own Role.
# Roles can be combined in any combination or all kept seperate.
# Follows python Enum patterns so the first Enum == 1 and doubles each time.
flag Roles:
    ADD_STRATEGY_MANAGER # can add strategies to the vault
    REVOKE_STRATEGY_MANAGER # can remove strategies from the vault
    FORCE_REVOKE_MANAGER # can force remove a strategy causing a loss
    ACCOUNTANT_MANAGER # can set the accountant that assesss fees
    QUEUE_MANAGER # can set the queue_manager
    REPORTING_MANAGER # calls report for strategies
    DEBT_MANAGER # adds and removes debt from strategies
    MAX_DEBT_MANAGER # can set the max debt for a strategy
    DEPOSIT_LIMIT_MANAGER # sets deposit limit for the vault
    MINIMUM_IDLE_MANAGER # sets the minimun total idle the vault should keep
    PROFIT_UNLOCK_MANAGER # sets the profit_max_unlock_time
    SWEEPER # can sweep tokens from the vault
    EMERGENCY_MANAGER # can shutdown vault in an emergency

flag StrategyChangeType:
    ADDED
    REVOKED

flag Rounding:
    ROUND_DOWN
    ROUND_UP

flag RoleStatusChange:
    OPENED
    CLOSED

# IMMUTABLE #
ASSET: immutable(IERC20)
DECIMALS: immutable(uint256)
FACTORY: public(immutable(address))

# STORAGE #
# HashMap that records all the strategies that are allowed to receive assets from the vault
strategies: public(HashMap[address, StrategyParams])

# ERC20 - amount of shares per account
balance_of: HashMap[address, uint256]
# ERC20 - owner -> (spender -> amount)
allowance: public(HashMap[address, HashMap[address, uint256]])
# Total amount of shares that are currently minted
# To get the ERC20 compliant version user totalSupply().
total_supply: public(uint256)

# Total amount of assets that has been deposited in strategies
total_debt: uint256
# Current assets held in the vault contract. Replacing balanceOf(this) to avoid price_per_share manipulation
total_idle: uint256
# Minimum amount of assets that should be kept in the vault contract to allow for fast, cheap redeems
minimum_total_idle: public(uint256)
# Maximum amount of tokens that the vault can accept. If totalAssets > deposit_limit, deposits will revert
deposit_limit: public(uint256)
# Contract that charges fees and can give refunds
accountant: public(address)
# Contract that will supply a optimal withdrawal queue of strategies
queue_manager: public(address)
# HashMap mapping addresses to their roles
roles: public(HashMap[address, Roles])
# HashMap mapping roles to their permissioned state. If false, the role is not open to the public
open_roles: public(HashMap[Roles, bool])
# Address that can add and remove addresses to roles 
role_manager: public(address)
# Temporary variable to store the address of the next role_manager until the role is accepted
future_role_manager: public(address)
# State of the vault - if set to true, only withdrawals will be available. It can't be reverted
shutdown: public(bool)

# ERC20 - name of the token
name: public(String[64])
# ERC20 - symbol of the token
symbol: public(String[32])

# The amount of time profits will unlock over
profit_max_unlock_time: uint256
# The timestamp of when the current unlocking period ends
full_profit_unlock_date: uint256
# The per second rate at which profit will unlcok
profit_unlocking_rate: uint256
# Last timestamp of the most recent _report() call
last_profit_update: uint256

# Last protocol fees were charged
last_report: uint256

# `nonces` track `permit` approvals with signature.
nonces: public(HashMap[address, uint256])
DOMAIN_TYPE_HASH: constant(bytes32) = keccak256('EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)')
PERMIT_TYPE_HASH: constant(bytes32) = keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)")

# Constructor
@deploy
def __init__(asset: IERC20, name: String[64], symbol: String[32], role_manager: address, profit_max_unlock_time: uint256):
    """
    @notice
        The constructor for the vault. Sets the asset, name, symbol, and role manager.
    @param asset
        The address of the asset that the vault will accept.
    @param name
        The name of the vault token.
    @param symbol
        The symbol of the vault token.
    @param role_manager 
        The address that can add and remove roles to addresses
    @param profit_max_unlock_time
        The maximum amount of time that the profit can be locked for
    """
    ASSET = asset
    DECIMALS = convert(staticcall IERC20Detailed(asset.address).decimals(), uint256)
    assert DECIMALS < 256 # dev: see VVE-2020-0001
    
    FACTORY = msg.sender

    # Must be > 0 so we can unlock shares
    assert profit_max_unlock_time > 0 # dev: profit unlock time too low
    # Must be less than one year for report cycles
    assert profit_max_unlock_time <= 31_556_952 # dev: profit unlock time too long
    self.profit_max_unlock_time = profit_max_unlock_time

    self.name = name
    self.symbol = symbol
    self.last_report = block.timestamp
    self.role_manager = role_manager
    self.shutdown = False

## SHARE MANAGEMENT ##
## ERC20 ##
@internal
def _spend_allowance(owner: address, spender: address, amount: uint256):
    # Unlimited approval does nothing (saves an SSTORE)
    current_allowance: uint256 = self.allowance[owner][spender]
    if (current_allowance < max_value(uint256)):
        assert current_allowance >= amount, "insufficient allowance"
        self._approve(owner, spender, current_allowance - amount)

@internal
def _transfer(sender: address, receiver: address, amount: uint256):
    assert self.balance_of[sender] >= amount, "insufficient funds"
    self.balance_of[sender] -= amount
    self.balance_of[receiver] += amount
    log Transfer(sender=sender, receiver=receiver, value=amount)

@internal
def _transfer_from(sender: address, receiver: address, amount: uint256) -> bool:
    self._spend_allowance(sender, msg.sender, amount)
    self._transfer(sender, receiver, amount)
    return True

@internal
def _approve(owner: address, spender: address, amount: uint256) -> bool:
    self.allowance[owner][spender] = amount
    log Approval(owner=owner, spender=spender, value=amount)
    return True

@internal
def _increase_allowance(owner: address, spender: address, amount: uint256) -> bool:
    self.allowance[owner][spender] += amount
    log Approval(owner=owner, spender=spender, value=self.allowance[owner][spender])
    return True

@internal
def _decrease_allowance(owner: address, spender: address, amount: uint256) -> bool:
    self.allowance[owner][spender] -= amount
    log Approval(owner=owner, spender=spender, value=self.allowance[owner][spender])
    return True

@internal
def _permit(owner: address, spender: address, amount: uint256, deadline: uint256, v: uint8, r: bytes32, s: bytes32) -> bool:
    assert owner != empty(address), "invalid owner"
    assert deadline >= block.timestamp, "permit expired"
    nonce: uint256 = self.nonces[owner]
    digest: bytes32 = keccak256(
        concat(
            b'\x19\x01',
            self.domain_separator(),
            keccak256(
                concat(
                    PERMIT_TYPE_HASH,
                    convert(owner, bytes32),
                    convert(spender, bytes32),
                    convert(amount, bytes32),
                    convert(nonce, bytes32),
                    convert(deadline, bytes32),
                )
            )
        )
    )
    assert ecrecover(digest, convert(v, uint256), convert(r, uint256), convert(s, uint256)) == owner, "invalid signature"
    self.allowance[owner][spender] = amount
    self.nonces[owner] = nonce + 1
    log Approval(owner=owner, spender=spender, value=amount)
    return True

@internal
def _burn_shares(shares: uint256, owner: address):
    self.balance_of[owner] -= shares
    self.total_supply -= shares
    log Transfer(sender=owner, receiver=empty(address), value=shares)

@view
@internal
def _unlocked_shares() -> uint256:
    # To avoid sudden price_per_share spikes, profit must be processed through an unlocking period.
    # The mechanism involves shares to be minted to the vault which are unlocked gradually over time.
    # Shares that have been locked are gradually unlocked over profit_max_unlock_time seconds
    _full_profit_unlock_date: uint256 = self.full_profit_unlock_date
    unlocked_shares: uint256 = 0
    if _full_profit_unlock_date > block.timestamp:
        unlocked_shares = self.profit_unlocking_rate * (block.timestamp - self.last_profit_update) // MAX_BPS_EXTENDED
    elif _full_profit_unlock_date != 0:
        # All shares have been unlocked
        unlocked_shares = self.balance_of[self]

    return unlocked_shares


@view
@internal
def _total_supply() -> uint256:
    return self.total_supply - self._unlocked_shares()

@internal
def _burn_unlocked_shares():
    """
    Burns shares that have been unlocked since last update. 
    In case the full unlocking period has passed, it stops the unlocking
    """
    unlocked_shares: uint256 = self._unlocked_shares()
    if unlocked_shares == 0:
        return

    # Only do an SSTORE if necessary
    if self.full_profit_unlock_date > block.timestamp:
        self.last_profit_update = block.timestamp

    self._burn_shares(unlocked_shares, self)

@view
@internal
def _total_assets() -> uint256:
    """
    Total amount of assets that are in the vault and in the strategies. 
    """
    return self.total_idle + self.total_debt

@view
@internal
def _convert_to_assets(shares: uint256, rounding: Rounding) -> uint256:
    """ 
    assets = shares * (total_assets / total_supply) --- (== price_per_share * shares)
    """
    total_supply: uint256 = self._total_supply()
    # if total_supply is 0, price_per_share is 1
    if total_supply == 0: 
        return shares

    numerator: uint256 = shares * self._total_assets()
    amount: uint256 = numerator // total_supply
    if rounding == Rounding.ROUND_UP and numerator % total_supply != 0:
        amount += 1

    return amount

@view
@internal
def _convert_to_shares(assets: uint256, rounding: Rounding) -> uint256:
    """
    shares = amount * (total_supply / total_assets) --- (== amount / price_per_share)
    """
    total_supply: uint256 = self._total_supply()
    total_assets: uint256 = self._total_assets()

    if total_assets == 0:
        # if total_assets and total_supply is 0, price_per_share is 1
        if total_supply == 0:
            return assets
        else:
            # Else if total_supply > 0 price_per_share is 0
            return 0

    numerator: uint256 = assets * total_supply
    shares: uint256 = numerator // total_assets
    if rounding == Rounding.ROUND_UP and numerator % total_assets != 0:
        shares += 1

    return shares


@internal
def erc20_safe_approve(token: address, spender: address, amount: uint256):
    # Used only to send tokens that are not the type managed by this Vault.
    # HACK: Used to handle non-compliant tokens like USDT
    response: Bytes[32] = raw_call(
        token,
        concat(
            method_id("approve(address,uint256)"),
            convert(spender, bytes32),
            convert(amount, bytes32),
        ),
        max_outsize=32,
    )
    if len(response) > 0:
        assert convert(response, bool), "Transfer failed!"


@internal
def erc20_safe_transfer_from(token: address, sender: address, receiver: address, amount: uint256):
    # Used only to send tokens that are not the type managed by this Vault.
    # HACK: Used to handle non-compliant tokens like USDT
    response: Bytes[32] = raw_call(
        token,
        concat(
            method_id("transferFrom(address,address,uint256)"),
            convert(sender, bytes32),
            convert(receiver, bytes32),
            convert(amount, bytes32),
        ),
        max_outsize=32,
    )
    if len(response) > 0:
        assert convert(response, bool), "Transfer failed!"

@internal
def erc20_safe_transfer(token: address, receiver: address, amount: uint256):
    # Used only to send tokens that are not the type managed by this Vault.
    # HACK: Used to handle non-compliant tokens like USDT
    response: Bytes[32] = raw_call(
        token,
        concat(
            method_id("transfer(address,uint256)"),
            convert(receiver, bytes32),
            convert(amount, bytes32),
        ),
        max_outsize=32,
    )
    if len(response) > 0:
        assert convert(response, bool), "Transfer failed!"

@internal
def _issue_shares(shares: uint256, recipient: address):
    self.balance_of[recipient] += shares
    self.total_supply += shares

    log Transfer(sender=empty(address), receiver=recipient, value=shares)

@internal
def _issue_shares_for_amount(amount: uint256, recipient: address) -> uint256:
    """
    Issues shares that are worth 'amount' in the underlying token (asset)
    WARNING: this takes into account that any new assets have been summed 
    to total_assets (otherwise pps will go down)
    """
    total_supply: uint256 = self._total_supply()
    total_assets: uint256 = self._total_assets()
    new_shares: uint256 = 0
    
    if total_supply == 0:
        new_shares = amount
    elif total_assets > amount:
        new_shares = amount * total_supply // (total_assets - amount)
    else:
        # If total_supply > 0 but amount = totalAssets we want to revert because
        # after first deposit, getting here would mean that the rest of the shares
        # would be diluted to a price_per_share of 0. Issuing shares would then mean
        # either the new depositer or the previous depositers will loose money.
        assert total_assets > amount, "amount too high"
  
    # We don't make the function revert
    if new_shares == 0:
       return 0

    self._issue_shares(new_shares, recipient)

    return new_shares

## ERC4626 ##
@view
@internal
def _max_deposit(receiver: address) -> uint256:
    _total_assets: uint256 = self._total_assets()
    _deposit_limit: uint256 = self.deposit_limit
    if (_total_assets >= _deposit_limit):
        return 0

    return _deposit_limit - _total_assets

@view
@internal
def _max_redeem(owner: address) -> uint256:
    if self.queue_manager != empty(address):
        # if a queue_manager is set we assume full redeems are possible
        return self.balance_of[owner]
    else:
        # NOTE: this will return the max amount that is available to redeem using ERC4626 
        # (which can only withdraw from the vault contract)
        return min(self.balance_of[owner], self._convert_to_shares(self.total_idle, Rounding.ROUND_DOWN))

@view
@internal
def _max_withdraw(owner: address) -> uint256:
    if self.queue_manager != empty(address):
        # if a queue_manager is set we assume full withdraws are possible
        return self._convert_to_assets(self.balance_of[owner], Rounding.ROUND_DOWN)
    else:
        # NOTE: this will return the max amount that is available to withdraw using ERC4626 
        # (which can only withdraw from the vault contract)
        return min(self._convert_to_assets(self.balance_of[owner], Rounding.ROUND_DOWN), self.total_idle)

@internal
def _deposit(sender: address, recipient: address, assets: uint256) -> uint256:
    assert self.shutdown == False # dev: shutdown
    assert recipient not in [self, empty(address)], "invalid recipient"

    assert self._total_assets() + assets <= self.deposit_limit, "exceed deposit limit"
 
    self.erc20_safe_transfer_from(ASSET.address, msg.sender, self, assets)
    self.total_idle += assets
   
    shares: uint256 = self._issue_shares_for_amount(assets, recipient)
    assert shares > 0, "cannot mint zero"

    log Deposit(sender=sender, owner=recipient, assets=assets, shares=shares)

    return shares

@view
@internal
def _assess_share_of_unrealised_losses(strategy: address, assets_needed: uint256) -> uint256:
    """
    Returns the share of losses that a user would take if withdrawing from this strategy
    e.g. if the strategy has unrealised losses for 10% of its current debt and the user 
    wants to withdraw 1000 tokens, the losses that he will take are 100 token
    """
    strategy_current_debt: uint256 = self.strategies[strategy].current_debt
    vault_shares: uint256 = staticcall IStrategy(strategy).balanceOf(self)
    strategy_assets: uint256 = staticcall IStrategy(strategy).convertToAssets(vault_shares)
    
    # If no losses, return 0
    if strategy_assets >= strategy_current_debt or strategy_current_debt == 0:
        return 0

    # user will withdraw assets_to_withdraw divided by loss ratio (strategy_assets / strategy_current_debt - 1)
    # but will only receive assets_to_withdraw
    # NOTE: if there are unrealised losses, the user will take his share
    losses_user_share: uint256 = assets_needed - assets_needed * strategy_assets // strategy_current_debt
    return losses_user_share

@internal
def _redeem(sender: address, receiver: address, owner: address, shares_to_burn: uint256, strategies: DynArray[address, 10]) -> uint256:
    shares: uint256 = shares_to_burn
    shares_balance: uint256 = self.balance_of[owner]

    assert shares > 0, "no shares to redeem"
    assert shares_balance >= shares, "insufficient shares to redeem"
    
    if sender != owner:
        self._spend_allowance(owner, sender, shares_to_burn)

    requested_assets: uint256 = self._convert_to_assets(shares, Rounding.ROUND_DOWN)

    # load to memory to save gas
    curr_total_idle: uint256 = self.total_idle
    
    # If there are not enough assets in the Vault contract, we try to free funds from strategies specified in the input
    if requested_assets > curr_total_idle:

        _strategies: DynArray[address, 10] = strategies

        queue_manager: address = self.queue_manager
        if queue_manager != empty(address):
            if len(_strategies) == 0:
                _strategies = extcall IQueueManager(queue_manager).withdraw_queue(self)

        # load to memory to save gas
        curr_total_debt: uint256 = self.total_debt

        # Withdraw from strategies if insufficient total idle
        assets_needed: uint256 = requested_assets - curr_total_idle
        assets_to_withdraw: uint256 = 0

        # NOTE: to compare against real withdrawals from strategies
        previous_balance: uint256 = staticcall ASSET.balanceOf(self)
        for strategy: address in _strategies:
            assert self.strategies[strategy].activation != 0, "inactive strategy"

            current_debt: uint256 = self.strategies[strategy].current_debt

            # What is the max amount to withdraw from this strategy.
            assets_to_withdraw = min(assets_needed, current_debt)

            # Cache max_withdraw for use if unrealized loss > 0
            max_withdraw: uint256 = staticcall IStrategy(strategy).maxWithdraw(self)

            # CHECK FOR UNREALISED LOSSES
            # If unrealised losses > 0, then the user will take the proportional share and realize it (required to avoid users withdrawing from lossy strategies) 
            # NOTE: strategies need to manage the fact that realising part of the loss can mean the realisation of 100% of the loss !! 
            #  (i.e. if for withdrawing 10% of the strategy it needs to unwind the whole position, generated losses might be bigger)
            unrealised_losses_share: uint256 = self._assess_share_of_unrealised_losses(strategy, assets_to_withdraw)
            if unrealised_losses_share > 0:
                # If max withdraw is limiting the amount to pull, we need to adjust the portion of 
                # the unrealized loss the user should take.
                if max_withdraw < assets_to_withdraw - unrealised_losses_share:
                    # How much would we want to withdraw
                    wanted: uint256 = assets_to_withdraw - unrealised_losses_share
                    # Get the proportion of unrealised comparing what we want vs. what we can get
                    unrealised_losses_share = unrealised_losses_share * max_withdraw // wanted
                    # Adjust assets_to_withdraw so all future calcultations work correctly
                    assets_to_withdraw = max_withdraw + unrealised_losses_share
                
                # User now "needs" less assets to be unlocked (as he took some as losses)
                assets_to_withdraw -= unrealised_losses_share
                requested_assets -= unrealised_losses_share
                # NOTE: done here instead of waiting for regular update of these values 
                # because it's a rare case (so we can save minor amounts of gas)
                assets_needed -= unrealised_losses_share
                curr_total_debt -= unrealised_losses_share

                # If max withdraw is 0 and unrealised loss is still > 0 then the strategy likely realized
                # a 100% loss and we will need to realize that loss before moving on.
                if max_withdraw == 0 and unrealised_losses_share > 0:
                    new_debt: uint256 = current_debt - unrealised_losses_share
        
                    # Update strategies storage
                    self.strategies[strategy].current_debt = new_debt
                    # Log the debt update
                    log DebtUpdated(
                        strategy=strategy,
                        current_debt=current_debt,
                        new_debt=new_debt
                    )

            # Adjust based on the max withdraw of the strategy
            assets_to_withdraw = min(assets_to_withdraw, max_withdraw)

            # Can't withdraw 0.
            if assets_to_withdraw == 0:
                continue
            
            # WITHDRAW FROM STRATEGY
            extcall IStrategy(strategy).withdraw(assets_to_withdraw, self, self)
            post_balance: uint256 = staticcall ASSET.balanceOf(self)
            
            # If we have not received what we expected, we consider the difference a loss
            loss: uint256 = 0
            if(previous_balance + assets_to_withdraw > post_balance):
                loss = previous_balance + assets_to_withdraw - post_balance

            # NOTE: strategy's debt decreases by the full amount but the total idle increases 
            # by the actual amount only (as the difference is considered lost)
            curr_total_idle += (assets_to_withdraw - loss)
            requested_assets -= loss
            curr_total_debt -= assets_to_withdraw

            # Vault will reduce debt because the unrealised loss has been taken by user
            new_debt: uint256 = current_debt - (assets_to_withdraw + unrealised_losses_share)
        
            # Update strategies storage
            self.strategies[strategy].current_debt = new_debt
            # Log the debt update
            log DebtUpdated(
                strategy=strategy,
                current_debt=current_debt,
                new_debt=new_debt
            )

            # NOTE: the user will receive less tokens (the rest were lost)
            # break if we have enough total idle to serve initial request 
            if requested_assets <= curr_total_idle:
                break

            # NOTE: we update the previous_balance variable here to save gas in next iteration
            previous_balance = post_balance

            # Reduce what we still need.
            assets_needed -= assets_to_withdraw

        # if we exhaust the queue and still have insufficient total idle, revert
        assert curr_total_idle >= requested_assets, "insufficient assets in vault"
        # commit memory to storage
        self.total_debt = curr_total_debt

    self._burn_shares(shares, owner)
    # commit memory to storage
    self.total_idle = curr_total_idle - requested_assets
    self.erc20_safe_transfer(ASSET.address, receiver, requested_assets)

    log Withdraw(
        sender=sender,
        receiver=receiver,
        owner=owner,
        assets=requested_assets,
        shares=shares
    )
    return requested_assets

## STRATEGY MANAGEMENT ##
@internal
def _add_strategy(new_strategy: address):
    assert new_strategy not in [self, empty(address)], "strategy cannot be zero address"
    assert staticcall IStrategy(new_strategy).asset() == ASSET.address, "invalid asset"
    assert self.strategies[new_strategy].activation == 0, "strategy already active"

    self.strategies[new_strategy] = StrategyParams(
        activation=block.timestamp,
        last_report=block.timestamp,
        current_debt=0,
        max_debt=0,
    )

    # we cache queue_manager since expected behavior is it being set
    queue_manager: address = self.queue_manager
    if queue_manager != empty(address):        
        # tell the queue_manager we have a new strategy
        extcall IQueueManager(queue_manager).new_strategy(new_strategy)

    log StrategyChanged(
        strategy=new_strategy,
        change_type=StrategyChangeType.ADDED
    )

@internal
def _revoke_strategy(strategy: address, force: bool=False):
    assert self.strategies[strategy].activation != 0, "strategy not active"
    loss: uint256 = 0
    
    if self.strategies[strategy].current_debt != 0:
        assert force, "strategy has debt"
        loss = self.strategies[strategy].current_debt
        self.total_debt -= loss
        log StrategyReported(
            strategy=strategy,
            gain=0,
            loss=loss,
            current_debt=0,
            protocol_fees=0,
            total_fees=0,
            total_refunds=0
        )

    # NOTE: strategy params are set to 0 (WARNING: it can be readded)
    self.strategies[strategy] = StrategyParams(
      activation=0,
      last_report=0,
      current_debt=0,
      max_debt=0,
    )

    # we cache queue_manager since expected behavior is it being set
    queue_manager: address = self.queue_manager
    if queue_manager != empty(address):
        # tell the queue_manager we removed a strategy
        extcall IQueueManager(queue_manager).remove_strategy(strategy)

    log StrategyChanged(
        strategy=strategy,
        change_type=StrategyChangeType.REVOKED
    )

# DEBT MANAGEMENT #
@internal
def _update_debt(strategy: address, target_debt: uint256) -> uint256:
    """
    The vault will rebalance the debt vs target debt. Target debt must be smaller or equal to strategy's max_debt.
    This function will compare the current debt with the target debt and will take funds or deposit new 
    funds to the strategy. 

    The strategy can require a maximum amount of funds that it wants to receive to invest. 
    The strategy can also reject freeing funds if they are locked.

    The vault will not invest the funds into the underlying protocol, which is responsibility of the strategy. 
    """
    new_debt: uint256 = target_debt

    current_debt: uint256 = self.strategies[strategy].current_debt

    if self.shutdown:
        new_debt = 0

    assert new_debt != current_debt, "new debt equals current debt"

    if current_debt > new_debt:
        # reduce debt
        assets_to_withdraw: uint256 = current_debt - new_debt

        # ensure we always have minimum_total_idle when updating debt
        minimum_total_idle: uint256 = self.minimum_total_idle
        total_idle: uint256 = self.total_idle
        
        # Respect minimum total idle in vault
        if total_idle + assets_to_withdraw < minimum_total_idle:
            assets_to_withdraw = minimum_total_idle - total_idle
            if assets_to_withdraw > current_debt:
                assets_to_withdraw = current_debt

        withdrawable: uint256 = staticcall IStrategy(strategy).maxWithdraw(self)
        assert withdrawable != 0, "nothing to withdraw"

        # if insufficient withdrawable, withdraw what we can
        if withdrawable < assets_to_withdraw:
            assets_to_withdraw = withdrawable

        # If there are unrealised losses we don't let the vault reduce its debt until there is a new report
        unrealised_losses_share: uint256 = self._assess_share_of_unrealised_losses(strategy, assets_to_withdraw)
        assert unrealised_losses_share == 0, "strategy has unrealised losses"
        
        pre_balance: uint256 = staticcall ASSET.balanceOf(self)
        extcall IStrategy(strategy).withdraw(assets_to_withdraw, self, self)
        post_balance: uint256 = staticcall ASSET.balanceOf(self)
        
        # making sure we are changing according to the real result no matter what. This will spend more gas but makes it more robust
        # also prevents issues from faulty strategy that either under or over delievers 'assets_to_withdraw'
        assets_to_withdraw = min(post_balance - pre_balance, current_debt)

        self.total_idle += assets_to_withdraw
        self.total_debt -= assets_to_withdraw
  
        new_debt = current_debt - assets_to_withdraw
    else:
        # Revert if target_debt cannot be achieved due to configured max_debt for given strategy
        assert new_debt <= self.strategies[strategy].max_debt, "target debt higher than max debt"

        # Vault is increasing debt with the strategy by sending more funds
        max_deposit: uint256 = staticcall IStrategy(strategy).maxDeposit(self)
        assert max_deposit != 0, "nothing to deposit"

        assets_to_deposit: uint256 = new_debt - current_debt
        if assets_to_deposit > max_deposit:
            assets_to_deposit = max_deposit
        
        # take into consideration minimum_total_idle
        minimum_total_idle: uint256 = self.minimum_total_idle
        total_idle: uint256 = self.total_idle

        assert total_idle > minimum_total_idle, "no funds to deposit"
        available_idle: uint256 = total_idle - minimum_total_idle

        # if insufficient funds to deposit, transfer only what is free
        if assets_to_deposit > available_idle:
            assets_to_deposit = available_idle

        if assets_to_deposit > 0:
            self.erc20_safe_approve(ASSET.address, strategy, assets_to_deposit)
            pre_balance: uint256 = staticcall ASSET.balanceOf(self)
            extcall IStrategy(strategy).deposit(assets_to_deposit, self)
            post_balance: uint256 = staticcall ASSET.balanceOf(self)
            self.erc20_safe_approve(ASSET.address, strategy, 0)

            # making sure we are changing according to the real result no matter what. 
            # This will spend more gas but makes it more robust
            assets_to_deposit = pre_balance - post_balance

            self.total_idle -= assets_to_deposit
            self.total_debt += assets_to_deposit

        new_debt = current_debt + assets_to_deposit

    # commit memory to storage
    self.strategies[strategy].current_debt = new_debt

    log DebtUpdated(
        strategy=strategy,
        current_debt=current_debt,
        new_debt=new_debt
    )
    return new_debt

@internal
def _assess_protocol_fees() -> (uint256, address):
    protocol_fees: uint256 = 0
    protocol_fee_recipient: address = empty(address)
    seconds_since_last_report: uint256 = block.timestamp - self.last_report
    # to avoid wasting gas for minimal fees vault will only assess once every PROTOCOL_FEE_ASSESSMENT_PERIOD seconds
    if(seconds_since_last_report >= PROTOCOL_FEE_ASSESSMENT_PERIOD):
        protocol_fee_bps: uint16 = 0
        protocol_fee_last_change: uint32 = 0

        protocol_fee_bps, protocol_fee_last_change, protocol_fee_recipient = staticcall IFactory(FACTORY).protocol_fee_config()

        if(protocol_fee_bps > 0):
            # NOTE: charge fees since last report OR last fee change (this will mean less fees are charged after a change in protocol_fees, but fees should not change frequently)
            seconds_since_last_report = min(seconds_since_last_report, block.timestamp - convert(protocol_fee_last_change, uint256))
            # fees = total_assets * protocol fees bpbs * time elapsed / seconds per year / max bps
            protocol_fees = self._total_assets() * convert(protocol_fee_bps, uint256) * seconds_since_last_report // 31_556_952 // MAX_BPS
            self.last_report = block.timestamp

    return (protocol_fees, protocol_fee_recipient)

## ACCOUNTING MANAGEMENT ##
@internal
def _process_report(strategy: address) -> (uint256, uint256):
    """
    Processing a report means comparing the debt that the strategy has taken with the current amount of funds it is reporting
    If the strategy owes less than it currently has, it means it has had a profit
    Else (assets < debt) it has had a loss

    Different strategies might choose different reporting strategies: pessimistic, only realised P&L, ...
    The best way to report depends on the strategy

    The profit will be distributed following a smooth curve over the next profit_max_unlock_time seconds. 
    Losses will be taken immediately, first from the profit buffer (avoiding an impact in pps), then will reduce pps
    """
    assert self.strategies[strategy].activation != 0, "inactive strategy"

    # Vault needs to assess 
    # Using strategy shares because some may be a ERC4626 vault
    strategy_shares: uint256 = staticcall IStrategy(strategy).balanceOf(self)
    total_assets: uint256 = staticcall IStrategy(strategy).convertToAssets(strategy_shares)
    current_debt: uint256 = self.strategies[strategy].current_debt
    
    # Burn shares that have been unlocked since the last update
    self._burn_unlocked_shares()

    gain: uint256 = 0
    loss: uint256 = 0

    if total_assets > current_debt:
        gain = total_assets - current_debt
    else:
        loss = current_debt - total_assets

    total_fees: uint256 = 0
    total_refunds: uint256 = 0

    accountant: address = self.accountant
    # if accountant is not set, fees and refunds remain unchanged
    if accountant != empty(address):
        total_fees, total_refunds = extcall IAccountant(accountant).report(strategy, gain, loss)

    # Protocol fee assessment
    protocol_fees: uint256 = 0
    protocol_fee_recipient: address = empty(address)
    protocol_fees, protocol_fee_recipient = self._assess_protocol_fees()
    total_fees += protocol_fees

    # We calculate the amount of shares that could be insta unlocked to avoid pps changes
    # NOTE: this needs to be done before any pps changes
    shares_to_burn: uint256 = 0
    accountant_fees_shares: uint256 = 0
    protocol_fees_shares: uint256 = 0
    if loss + total_fees > 0:
        shares_to_burn += self._convert_to_shares(loss + total_fees, Rounding.ROUND_UP)
        # Vault calculates the amount of shares to mint as fees before changing totalAssets / totalSupply
        if total_fees > 0:
            accountant_fees_shares = self._convert_to_shares(total_fees - protocol_fees, Rounding.ROUND_DOWN)
            if protocol_fees > 0:
              protocol_fees_shares = self._convert_to_shares(protocol_fees, Rounding.ROUND_DOWN)

    newly_locked_shares: uint256 = 0
    if total_refunds > 0:
        # if refunds are non-zero, transfer shares worth of assets
        total_refunds_shares: uint256 = min(self._convert_to_shares(total_refunds, Rounding.ROUND_UP), self.balance_of[accountant])
        # Shares received as a refund are locked to avoid sudden pps change (like profits)
        self._transfer(accountant, self, total_refunds_shares)
        newly_locked_shares += total_refunds_shares

    if gain > 0:
        # NOTE: this will increase total_assets
        self.strategies[strategy].current_debt += gain
        self.total_debt += gain

        # NOTE: vault will issue shares worth the profit to avoid instant pps change
        newly_locked_shares += self._issue_shares_for_amount(gain, self)

    # Strategy is reporting a loss
    if loss > 0:
        self.strategies[strategy].current_debt -= loss
        self.total_debt -= loss

    # NOTE: should be precise (no new unlocked shares due to above's burn of shares)
    # newly_locked_shares have already been minted / transfered to the vault, so they need to be substracted
    # no risk of underflow because they have just been minted
    previously_locked_shares: uint256 = self.balance_of[self] - newly_locked_shares

    # Now that pps has updated, we can burn the shares we intended to burn as a result of losses/fees.
    # NOTE: If a value reduction (losses / fees) has occured, prioritize burning locked profit to avoid
    # negative impact on price per share. Price per share is reduced only if losses exceed locked value.
    if shares_to_burn > 0:
        shares_to_burn = min(shares_to_burn, previously_locked_shares + newly_locked_shares)
        self._burn_shares(shares_to_burn, self)
        # we burn first the newly locked shares, then the previously locked shares
        shares_not_to_lock: uint256 = min(shares_to_burn, newly_locked_shares)
        newly_locked_shares -= shares_not_to_lock
        previously_locked_shares -= (shares_to_burn - shares_not_to_lock)

    # issue shares that were calculated above
    if accountant_fees_shares > 0:
        self._issue_shares(accountant_fees_shares, accountant)

    if protocol_fees_shares > 0:
        self._issue_shares(protocol_fees_shares, protocol_fee_recipient)

    # Update unlocking rate and time to fully unlocked
    total_locked_shares: uint256 = previously_locked_shares + newly_locked_shares
    _profit_max_unlock_time: uint256 = self.profit_max_unlock_time
    if total_locked_shares > 0:

        # Calculate how long until the full amount of shares is unlocked
        remaining_time: uint256 = 0
        _full_profit_unlock_date: uint256 = self.full_profit_unlock_date
        if _full_profit_unlock_date > block.timestamp: 
            remaining_time = _full_profit_unlock_date - block.timestamp

        # new_profit_locking_period is a weighted average between the remaining time of the previously locked shares and the profit_max_unlock_time
        new_profit_locking_period: uint256 = (previously_locked_shares * remaining_time + newly_locked_shares * _profit_max_unlock_time) // total_locked_shares
        self.profit_unlocking_rate = total_locked_shares * MAX_BPS_EXTENDED // new_profit_locking_period
        self.full_profit_unlock_date = block.timestamp + new_profit_locking_period
        self.last_profit_update = block.timestamp

    else:
        # NOTE: only setting this to 0 will turn in the desired effect, no need to update last_profit_update or full_profit_unlock_date
        self.profit_unlocking_rate = 0

    self.strategies[strategy].last_report = block.timestamp

    # We have to recalculate the fees paid for cases with an overall loss
    log StrategyReported(
        strategy=strategy,
        gain=gain,
        loss=loss,
        current_debt=self.strategies[strategy].current_debt,
        protocol_fees=self._convert_to_assets(protocol_fees_shares, Rounding.ROUND_DOWN),
        total_fees=self._convert_to_assets(protocol_fees_shares + accountant_fees_shares, Rounding.ROUND_DOWN),
        total_refunds=total_refunds
    )

    return (gain, loss)


# SETTERS #
@external
def set_accountant(new_accountant: address):
    """
    @notice Set the new accountant address.
    @param new_accountant The new accountant address.
    """
    self._enforce_role(msg.sender, Roles.ACCOUNTANT_MANAGER)
    self.accountant = new_accountant
    log UpdateAccountant(accountant=new_accountant)

@external
def set_queue_manager(new_queue_manager: address):
    """
    @notice Set the new queue manager address.
    @param new_queue_manager The new queue manager address.
    """
    self._enforce_role(msg.sender, Roles.QUEUE_MANAGER)
    self.queue_manager = new_queue_manager
    log UpdateQueueManager(queue_manager=new_queue_manager)

@external
def set_deposit_limit(deposit_limit: uint256):
    """
    @notice Set the new deposit limit.
    @dev can not be changed if shutdown.
    @param deposit_limit The new deposit limit.
    """
    assert self.shutdown == False # Dev: shutdown
    self._enforce_role(msg.sender, Roles.DEPOSIT_LIMIT_MANAGER)
    self.deposit_limit = deposit_limit
    log UpdateDepositLimit(deposit_limit=deposit_limit)

@external
def set_minimum_total_idle(minimum_total_idle: uint256):
    """
    @notice Set the new minimum total idle.
    @param minimum_total_idle The new minimum total idle.
    """
    self._enforce_role(msg.sender, Roles.MINIMUM_IDLE_MANAGER)
    self.minimum_total_idle = minimum_total_idle
    log UpdateMinimumTotalIdle(minimum_total_idle=minimum_total_idle)

@external
def set_profit_max_unlock_time(new_profit_max_unlock_time: uint256):
    """
    @notice Set the new profit max unlock time.
    @dev The time is denominated in seconds and must be more than 0
        and less than 1 year. We don't need to update locking period
        since the current period will use the old rate and on the next
        report it will be reset with the new unlocking time.
    @param new_profit_max_unlock_time The new profit max unlock time.
    """
    self._enforce_role(msg.sender, Roles.PROFIT_UNLOCK_MANAGER)
    
    # Must be > 0 so we can unlock shares
    assert new_profit_max_unlock_time > 0, "profit unlock time too low"
    # Must be less than one year for report cycles
    assert new_profit_max_unlock_time <= 31_556_952, "profit unlock time too long"

    self.profit_max_unlock_time = new_profit_max_unlock_time
    log UpdateProfitMaxUnlockTime(profit_max_unlock_time=new_profit_max_unlock_time)

# ROLE MANAGEMENT #
@internal
def _enforce_role(account: address, role: Roles):
    assert role in self.roles[account] or self.open_roles[role], "not allowed"

@external
def set_role(account: address, role: Roles):
    """
    @notice Set the role of an account.
    @param account The account to set the role for.
    @param role The role to set.
    """
    assert msg.sender == self.role_manager
    self.roles[account] = role
    log RoleSet(account=account, role=role)

@external
def set_open_role(role: Roles):
    """
    @notice Set the role to be open.
    @param role The role to set.
    """
    assert msg.sender == self.role_manager
    self.open_roles[role] = True
    log RoleStatusChanged(role=role, status=RoleStatusChange.OPENED)

@external
def close_open_role(role: Roles):
    """
    @notice Close the role.
    @param role The role to close.
    """
    assert msg.sender == self.role_manager
    self.open_roles[role] = False
    log RoleStatusChanged(role=role, status=RoleStatusChange.CLOSED)
    
@external
def transfer_role_manager(role_manager: address):
    """
    @notice Transfer the role manager to a new address.
    @param role_manager The new role manager address.
    """
    assert msg.sender == self.role_manager
    self.future_role_manager = role_manager

@external
def accept_role_manager():
    """
    @notice Accept the role manager transfer.
    """
    assert msg.sender == self.future_role_manager
    self.role_manager = msg.sender
    self.future_role_manager = empty(address)
    log UpdateRoleManager(role_manager=msg.sender)

# VAULT STATUS VIEWS
@view
@external
def unlocked_shares() -> uint256:
    """
    @notice Get the amount of shares that are not locked.
    @return The amount of shares that are not locked.
    """
    return self._unlocked_shares()

@view
@external
def pricePerShare() -> uint256:
    """
    @notice Get the price per share.
    @dev This value offers limited precision. Integrations the require 
    exact precision should use convertToAssets or convertToShares instead.
    @return The price per share.
    """
    return self._convert_to_assets(10 ** DECIMALS, Rounding.ROUND_DOWN)


@view
@external
def availableDepositLimit() -> uint256:
    """
    @notice Get the available deposit limit.
    @return The available deposit limit.
    """
    if self.deposit_limit > self._total_assets():
        return self.deposit_limit - self._total_assets()
    return 0

## REPORTING MANAGEMENT ##
@external
def process_report(strategy: address) -> (uint256, uint256):
    """
    @notice Process the report of a strategy.
    @param strategy The strategy to process the report for.
    @return The gain and loss of the strategy.
    """
    self._enforce_role(msg.sender, Roles.REPORTING_MANAGER)
    return self._process_report(strategy)

@external
@nonreentrant
def sweep(token: address) -> (uint256):
    """
    @notice Sweep the token from airdop or sent by mistake.
    @param token The token to sweep.
    @return The amount of dust swept.
    """
    self._enforce_role(msg.sender, Roles.SWEEPER)
    assert token != self, "can't sweep self"
    assert self.strategies[token].activation == 0, "can't sweep strategy"
    amount: uint256 = 0
    if token == ASSET.address:
        amount = staticcall ASSET.balanceOf(self) - self.total_idle
    else:
        amount = staticcall IERC20(token).balanceOf(self)
    assert amount != 0, "no dust"
    self.erc20_safe_transfer(token, msg.sender, amount)
    log Sweep(token=token, amount=amount)
    return amount

## STRATEGY MANAGEMENT ##
@external
def add_strategy(new_strategy: address):
    """
    @notice Add a new strategy.
    @param new_strategy The new strategy to add.
    """
    self._enforce_role(msg.sender, Roles.ADD_STRATEGY_MANAGER)
    self._add_strategy(new_strategy)

@external
def revoke_strategy(strategy: address):
    """
    @notice Revoke a strategy.
    @param strategy The strategy to revoke.
    """
    self._enforce_role(msg.sender, Roles.REVOKE_STRATEGY_MANAGER)
    self._revoke_strategy(strategy)

@external
def force_revoke_strategy(strategy: address):
    """
    @notice Force revoke a strategy.
    @param strategy The strategy to force revoke.
    @dev The vault will remove the inputed strategy and write off any debt left in it as loss. 
    This function is a dangerous function as it can force a strategy to take a loss. 
    All possible assets should be removed from the strategy first via update_debt
    Note that if a strategy is removed erroneously it can be re-added and the loss will be credited as profit. Fees will apply
    """
    self._enforce_role(msg.sender, Roles.FORCE_REVOKE_MANAGER)
    self._revoke_strategy(strategy, True)

## DEBT MANAGEMENT ##
@external
def update_max_debt_for_strategy(strategy: address, new_max_debt: uint256):
    """
    @notice Update the max debt for a strategy.
    @param strategy The strategy to update the max debt for.
    @param new_max_debt The new max debt for the strategy.
    """
    self._enforce_role(msg.sender, Roles.MAX_DEBT_MANAGER)
    assert self.strategies[strategy].activation != 0, "inactive strategy"
    self.strategies[strategy].max_debt = new_max_debt
    log UpdatedMaxDebtForStrategy(
        sender=msg.sender,
        strategy=strategy,
        new_debt=new_max_debt
    )

@external
@nonreentrant
def update_debt(strategy: address, target_debt: uint256) -> uint256:
    """
    @notice Update the debt for a strategy.
    @param strategy The strategy to update the debt for.
    @param target_debt The target debt for the strategy.
    @return The amount of debt added or removed.
    """
    self._enforce_role(msg.sender, Roles.DEBT_MANAGER)
    return self._update_debt(strategy, target_debt)

## EMERGENCY MANAGEMENT ##
@external
def shutdown_vault():
    """
    @notice Shutdown the vault.
    """
    self._enforce_role(msg.sender, Roles.EMERGENCY_MANAGER)
    assert self.shutdown == False
    
    # Shutdown the vault.
    self.shutdown = True

    # Set deposit limit to 0.
    self.deposit_limit = 0
    log UpdateDepositLimit(deposit_limit=0)

    self.roles[msg.sender] = self.roles[msg.sender] | Roles.DEBT_MANAGER
    log Shutdown()


## SHARE MANAGEMENT ##
## ERC20 + ERC4626 ##
@external
@nonreentrant
def deposit(assets: uint256, receiver: address) -> uint256:
    """
    @notice Deposit assets into the vault.
    @param assets The amount of assets to deposit.
    @param receiver The address to receive the shares.
    @return The amount of shares minted.
    """
    return self._deposit(msg.sender, receiver, assets)

@external
@nonreentrant
def mint(shares: uint256, receiver: address) -> uint256:
    """
    @notice Mint shares for the receiver.
    @param shares The amount of shares to mint.
    @param receiver The address to receive the shares.
    @return The amount of assets deposited.
    """
    assets: uint256 = self._convert_to_assets(shares, Rounding.ROUND_UP)
    self._deposit(msg.sender, receiver, assets)
    return assets

@external
@nonreentrant
def withdraw(assets: uint256, receiver: address, owner: address, strategies: DynArray[address, 10] = []) -> uint256:
    """
    @notice Withdraw an amount of asset to `receiver` burning `owner`s shares.
    @param assets The amount of asset to withdraw.
    @param receiver The address to receive the assets.
    @param owner The address whos shares are being burnt.
    @param strategies Optional array of strategies to withdraw from.
    @return The amount of shares actually burnt.
    """
    shares: uint256 = self._convert_to_shares(assets, Rounding.ROUND_UP)
    self._redeem(msg.sender, receiver, owner, shares, strategies)
    return shares

@external
@nonreentrant
def redeem(shares: uint256, receiver: address, owner: address, strategies: DynArray[address, 10] = []) -> uint256:
    """
    @notice Redeems an amount of shares of `owners` shares sending funds to `receiver`.
    @param shares The amount of shares to burn.
    @param receiver The address to receive the assets.
    @param owner The address whos shares are being burnt.
    @param strategies Optional array of strategies to withdraw from.
    @return The amount of assets actually withdrawn.
    """
    assets: uint256 = self._redeem(msg.sender, receiver, owner, shares, strategies)
    return assets

@external
def approve(spender: address, amount: uint256) -> bool:
    """
    @notice Approve an address to spend the vault's shares.
    @param spender The address to approve.
    @param amount The amount of shares to approve.
    @return True if the approval was successful.
    """
    return self._approve(msg.sender, spender, amount)

@external
def transfer(receiver: address, amount: uint256) -> bool:
    """
    @notice Transfer shares to a receiver.
    @param receiver The address to transfer shares to.
    @param amount The amount of shares to transfer.
    @return True if the transfer was successful.
    """
    assert receiver not in [self, empty(address)]
    self._transfer(msg.sender, receiver, amount)
    return True

@external
def transferFrom(sender: address, receiver: address, amount: uint256) -> bool:
    """
    @notice Transfer shares from a sender to a receiver.
    @param sender The address to transfer shares from.
    @param receiver The address to transfer shares to.
    @param amount The amount of shares to transfer.
    @return True if the transfer was successful.
    """
    assert receiver not in [self, empty(address)]
    return self._transfer_from(sender, receiver, amount)

## ERC20+4626 compatibility
@external
def increaseAllowance(spender: address, amount: uint256) -> bool:
    """
    @notice Increase the allowance for a spender.
    @param spender The address to increase the allowance for.
    @param amount The amount to increase the allowance by.
    @return True if the increase was successful.
    """
    return self._increase_allowance(msg.sender, spender, amount)

@external
def decreaseAllowance(spender: address, amount: uint256) -> bool:
    """
    @notice Decrease the allowance for a spender.
    @param spender The address to decrease the allowance for.
    @param amount The amount to decrease the allowance by.
    @return True if the decrease was successful.
    """
    return self._decrease_allowance(msg.sender, spender, amount)

@external
def permit(owner: address, spender: address, amount: uint256, deadline: uint256, v: uint8, r: bytes32, s: bytes32) -> bool:
    """
    @notice Approve an address to spend the vault's shares.
    @param owner The address to approve.
    @param spender The address to approve.
    @param amount The amount of shares to approve.
    @param deadline The deadline for the permit.
    @param v The v component of the signature.
    @param r The r component of the signature.
    @param s The s component of the signature.
    @return True if the approval was successful.
    """
    return self._permit(owner, spender, amount, deadline, v, r, s)

@view
@external
def balanceOf(addr: address) -> uint256:
    """
    @notice Get the balance of a user.
    @param addr The address to get the balance of.
    @return The balance of the user.
    """
    if(addr == self):
      return self.balance_of[addr] - self._unlocked_shares()
    return self.balance_of[addr]

@view
@external
def totalSupply() -> uint256:
    """
    @notice Get the total supply of shares.
    @return The total supply of shares.
    """
    return self._total_supply()

@view
@external
def asset() -> address:
    """
    @notice Get the address of the asset.
    @return The address of the asset.
    """
    return ASSET.address

@view
@external
def decimals() -> uint8:
    """
    @notice Get the number of decimals of the asset/share.
    @return The number of decimals of the asset/share.
    """
    return convert(DECIMALS, uint8)

@view
@external
def totalAssets() -> uint256:
    """
    @notice Get the total assets held by the vault.
    @return The total assets held by the vault.
    """
    return self._total_assets()

@view
@external
def totalIdle() -> uint256:
    """
    @notice Get the amount of loose `asset` the vault holds.
    @return The current total idle.
    """
    return self.total_idle

@view
@external
def totalDebt() -> uint256:
    """
    @notice Get the the total amount of funds invested
    across all strategies.
    @return The current total debt.
    """
    return self.total_debt

@view
@external
def convertToShares(assets: uint256) -> uint256:
    """
    @notice Convert an amount of assets to shares.
    @param assets The amount of assets to convert.
    @return The amount of shares.
    """
    return self._convert_to_shares(assets, Rounding.ROUND_DOWN)

@view
@external
def previewDeposit(assets: uint256) -> uint256:
    """
    @notice Preview the amount of shares that would be minted for a deposit.
    @param assets The amount of assets to deposit.
    @return The amount of shares that would be minted.
    """
    return self._convert_to_shares(assets, Rounding.ROUND_DOWN)

@view
@external
def previewMint(shares: uint256) -> uint256:
    """
    @notice Preview the amount of assets that would be deposited for a mint.
    @param shares The amount of shares to mint.
    @return The amount of assets that would be deposited.
    """
    return self._convert_to_assets(shares, Rounding.ROUND_UP)

@view
@external
def convertToAssets(shares: uint256) -> uint256:
    """
    @notice Convert an amount of shares to assets.
    @param shares The amount of shares to convert.
    @return The amount of assets.
    """
    return self._convert_to_assets(shares, Rounding.ROUND_DOWN)

@view
@external
def maxDeposit(receiver: address) -> uint256:
    """
    @notice Get the maximum amount of assets that can be deposited.
    @param receiver The address that will receive the shares.
    @return The maximum amount of assets that can be deposited.
    """
    return self._max_deposit(receiver)

@view
@external
def maxMint(receiver: address) -> uint256:
    """
    @notice Get the maximum amount of shares that can be minted.
    @param receiver The address that will receive the shares.
    @return The maximum amount of shares that can be minted.
    """
    max_deposit: uint256 = self._max_deposit(receiver)
    return self._convert_to_shares(max_deposit, Rounding.ROUND_DOWN)

@view
@external
def maxWithdraw(owner: address) -> uint256:
    """
    @notice Get the maximum amount of assets that can be withdrawn.
    @param owner The address that owns the shares.
    @return The maximum amount of assets that can be withdrawn.
    """
    # NOTE: if a queue_manager is not set a withdraw function that complies with ERC4626 won't withdraw from strategies, 
    #       so this will just uses liquidity available in the vault contract
    return self._max_withdraw(owner)

@view
@external
def maxRedeem(owner: address) -> uint256:
    """
    @notice Get the maximum amount of shares that can be redeemed.
    @param owner The address that owns the shares.
    @return The maximum amount of shares that can be redeemed.
    """
    # NOTE: if a queue_manager is not set a redeem function that complies with ERC4626 won't withdraw from strategies, 
    #       so this will just uses liquidity available in the vault contract
    return self._max_redeem(owner)

@view
@external
def previewWithdraw(assets: uint256) -> uint256:
    """
    @notice Preview the amount of shares that would be redeemed for a withdraw.
    @param assets The amount of assets to withdraw.
    @return The amount of shares that would be redeemed.
    """
    return self._convert_to_shares(assets, Rounding.ROUND_UP)

@view
@external
def previewRedeem(shares: uint256) -> uint256:
    """
    @notice Preview the amount of assets that would be withdrawn for a redeem.
    @param shares The amount of shares to redeem.
    @return The amount of assets that would be withdrawn.
    """
    return self._convert_to_assets(shares, Rounding.ROUND_DOWN)

@view
@external
def api_version() -> String[28]:
    """
    @notice Get the API version of the vault.
    @return The API version of the vault.
    """
    return API_VERSION

@view
@external
def assess_share_of_unrealised_losses(strategy: address, assets_needed: uint256) -> uint256:
    """
    @notice Assess the share of unrealised losses that a strategy has.
    @param strategy The address of the strategy.
    @param assets_needed The amount of assets needed to be withdrawn.
    @return The share of unrealised losses that the strategy has.
    """
    assert self.strategies[strategy].current_debt >= assets_needed

    return self._assess_share_of_unrealised_losses(strategy, assets_needed)

## Profit locking getter functions ##

@view
@external
def profitMaxUnlockTime() -> uint256:
    """
    @notice Gets the current time profits are set to unlock over.
    @return The current profit max unlock time.
    """
    return self.profit_max_unlock_time

@view
@external
def fullProfitUnlockDate() -> uint256:
    """
    @notice Gets the timestamp at which all profits will be unlocked.
    @return The full profit unlocking timestamp
    """
    return self.full_profit_unlock_date

@view
@external
def profitUnlockingRate() -> uint256:
    """
    @notice The per second rate at which profits are unlocking.
    @dev This is denominated in EXTENDED_BPS decimals.
    @return The current profit unlocking rate.
    """
    return self.profit_unlocking_rate

@view
@external
def lastReport() -> uint256:
    """
    @notice The timestamp of the last time protocol fees were charged.
    @return The last report.
    """
    return self.last_report

# eip-1344
@view
@internal
def domain_separator() -> bytes32:
    return keccak256(
        concat(
            DOMAIN_TYPE_HASH,
            keccak256(convert("Yearn Vault", Bytes[11])),
            keccak256(convert(API_VERSION, Bytes[28])),
            convert(chain.id, bytes32),
            convert(self, bytes32)
        )
    )

@view
@external
def DOMAIN_SEPARATOR() -> bytes32:
    """
    @notice Get the domain separator.
    @return The domain separator.
    """
    return self.domain_separator()
