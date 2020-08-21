# @dev Implementation of ERC-201 token standard.
# @author neoJeff

from vyper.interfaces import ERC201

implements: ERC201

event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    value: uint256

# NOTE: don't need this
# event Buy:
#     buyer: indexed(address)
#     buy_order: uint256

# event Sell:
#     seller: indexed(address)
#     sell_order: uint256


name: public(String[64])
symbol: public(String[32])
decimals: public(uint256)

# NOTE: By declaring `balanceOf` as public, vyper automatically generates a 'balanceOf()' getter
#       method to allow access to account balances.
#       The _KeyType will become a required parameter for the getter and it will return _ValueType.
#       See: https://vyper.readthedocs.io/en/v0.1.0-beta.8/types.html?highlight=getter#mappings
balanceOf: public(HashMap[address, uint256])
allowances: HashMap[address, HashMap[address, uint256]]
total_supply: uint256
minter: address
price: uint256


@external
def __init__(_name: String[64], _symbol: String[32], _decimals: uint256, _supply: uint256, _price: uint256):
    init_supply: uint256 = _supply * 10 ** _decimals
    self.name = _name
    self.symbol = _symbol
    self.decimals = _decimals
    self.balanceOf[msg.sender] = init_supply
    # total_supply should equal 0 but leave for now
    self.total_supply = init_supply
    self.minter = msg.sender
    self.price = _price
    log Transfer(ZERO_ADDRESS, msg.sender, init_supply)


@view
@external
def totalSupply() -> uint256:
    """
    @dev Total number of tokens in existence.
    """
    return self.total_supply


@external
def transfer(_to : address, _value : uint256) -> bool:
    """
    @dev Transfer token for a specified address
    @param _to The address to transfer to.
    @param _value The amount to be transferred.
    @param _confirm confirms sending coins
    """
    # NOTE: vyper does not allow underflows
    #       so the following subtraction would revert on insufficient balance
    assert msg.sender == self.minter
    self.balanceOf[msg.sender] -= _value
    self.balanceOf[_to] += _value
    log Transfer(msg.sender, _to, _value)
    return True


@internal
def _mint(_to: address, _value: uint256):
    """
    @dev Mint an amount of the token and assigns it to an account.
         This encapsulates the modification of balances such that the
         proper events are emitted.
    @param _to The account that will receive the created tokens.
    @param _value The amount that will be created.
    """
    assert _to != ZERO_ADDRESS
    self.total_supply += _value
    self.balanceOf[_to] += _value
    log Transfer(ZERO_ADDRESS, _to, _value)


@external
def mint(_value: uint256):
    """
    @dev Mint an amount of the token of msg.sender.
    @param _value The amount that will be minted.
    """
    assert msg.sender == self.minter
    self._mint(msg.sender, _value)


@external
def mintTo(_to: address, _value: uint256):
    """
    @dev Mint an amount of the token from a given account.
    @param _to The account whose tokens will be minted.
    @param _value The amount that will be minted.
    """
    self.allowances[_to][msg.sender] += _value
    self._mint(_to, _value)


@internal
def _burn(_to: address, _value: uint256):
    """
    @dev Internal function that burns an amount of the token of a given
         account.
    @param _to The account whose tokens will be burned.
    @param _value The amount that will be burned.
    """
    assert _to != ZERO_ADDRESS
    self.total_supply -= _value
    self.balanceOf[_to] -= _value
    log Transfer(_to, ZERO_ADDRESS, _value)


@external
def burn(_value: uint256):
    """
    @dev Burn an amount of the token of msg.sender.
    @param _value The amount that will be burned.
    """
    self._burn(msg.sender, _value)


@external
def burnFrom(_to: address, _value: uint256):
    """
    @dev Burn an amount of the token from a given account.
    @param _to The account whose tokens will be burned.
    @param _value The amount that will be burned.
    """
    self.allowances[_to][msg.sender] -= _value
    self._burn(_to, _value)