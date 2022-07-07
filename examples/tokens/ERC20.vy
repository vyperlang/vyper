# @dev Implementation of ERC-20 token standard.
# @author Takayuki Jimba (@yudetamago)
# https://github.com/ethereum/EIPs/blob/master/EIPS/eip-20.md

from vyper.interfaces import ERC20
from vyper.interfaces import ERC20Detailed

implements: ERC20
implements: ERC20Detailed

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    value: uint256

name: public(String[32])
symbol: public(String[32])
decimals: public(uint8)

# NOTE: By declaring `balanceOf` as public, vyper automatically generates a 'balanceOf()' getter
#       method to allow access to account balances.
#       The _KeyType will become a required parameter for the getter and it will return _ValueType.
#       See: https://vyper.readthedocs.io/en/v0.1.0-beta.8/types.html?highlight=getter#mappings
balanceOf: public(HashMap[address, uint256])
# By declaring `allowance` as public, vyper automatically generates the `allowance()` getter
allowance: public(HashMap[address, HashMap[address, uint256]])
# By declaring `totalSupply` as public, we automatically create the `totalSupply()` getter
totalSupply: public(uint256)
minter: address


@external
def __init__(name: String[32], symbol: String[32], decimals: uint8, supply: uint256):
    init_supply: uint256 = supply * 10 ** convert(decimals, uint256)
    self.name = name
    self.symbol = symbol
    self.decimals = decimals
    self.balanceOf[msg.sender] = init_supply
    self.totalSupply = init_supply
    self.minter = msg.sender
    log Transfer(ZERO_ADDRESS, msg.sender, init_supply)



@external
def transfer(receiver: address, amount: uint256) -> bool:
    """
    @dev Transfer token for a specified address
    @param receiver The address to transfer to.
    @param amount The amount to be transferred.
    """
    # NOTE: vyper does not allow underflows
    #       so the following subtraction would revert on insufficient balance
    self.balanceOf[msg.sender] -= amount
    self.balanceOf[receiver] += amount
    log Transfer(msg.sender, receiver, amount)
    return True


@external
def transferFrom(holder: address, receiver: address, amount: uint256) -> bool:
    """
     @dev Transfer tokens from one address to another.
     @param holder address The address which you want to send tokens from
     @param receiver address The address which you want to transfer to
     @param amount uint256 the amount of tokens to be transferred
    """
    # NOTE: vyper does not allow underflows
    #       so the following subtraction would revert on insufficient balance
    self.balanceOf[holder] -= amount
    self.balanceOf[receiver] += amount
    # NOTE: vyper does not allow underflows
    #      so the following subtraction would revert on insufficient allowance
    self.allowance[holder][msg.sender] -= amount
    log Transfer(holder, receiver, amount)
    return True


@external
def approve(spender: address, amount: uint256) -> bool:
    """
    @dev Approve the passed address to spend the specified amount of tokens on behalf of msg.sender.
         Beware that changing an allowance with this method brings the risk that someone may use both the old
         and the new allowance by unfortunate transaction ordering. One possible solution to mitigate this
         race condition is to first reduce the spender's allowance to 0 and set the desired value afterwards:
         https://github.com/ethereum/ei_ps/issues/20#issuecomment-263524729
    @param spender The address which will spend the funds.
    @param amount The amount of tokens to be spent.
    """
    self.allowance[msg.sender][spender] = amount
    log Approval(msg.sender, spender, amount)
    return True


@external
def mint(receiver: address, amount: uint256):
    """
    @dev Mint an amount of the token and assigns it to an account.
         This encapsulates the modification of balances such that the
         proper events are emitted.
    @param receiver The account that will receive the created tokens.
    @param amount The amount that will be created.
    """
    assert msg.sender == self.minter
    assert receiver != ZERO_ADDRESS
    self.totalSupply += amount
    self.balanceOf[receiver] += amount
    log Transfer(ZERO_ADDRESS, receiver, amount)


@internal
def _burn(account: address, amount: uint256):
    """
    @dev Internal function that burns an amount of the token of a given
         account.
    @param account The account whose tokens will be burned.
    @param amount The amount that will be burned.
    """
    assert account != ZERO_ADDRESS
    self.totalSupply -= amount
    self.balanceOf[account] -= amount
    log Transfer(account, ZERO_ADDRESS, amount)


@external
def burn(amount: uint256):
    """
    @dev Burn an amount of the token of msg.sender.
    @param amount The amount that will be burned.
    """
    self._burn(msg.sender, amount)


@external
def burn_from(account: address, amount: uint256):
    """
    @dev Burn an amount of the token from a given account.
    @param account The account whose tokens will be burned.
    @param amount The amount that will be burned.
    """
    self.allowance[account][msg.sender] -= amount
    self._burn(account, amount)
