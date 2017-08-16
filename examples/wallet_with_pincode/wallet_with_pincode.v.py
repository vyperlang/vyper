# Simple wallet with PIN protection

# bad guys can not get money out of this contract-wallet
# even if your secret key has been compromised
# if they do not know the `secret`
# (pre-image of the hash that is stored in contract).

# Owners wallet.
owner: public(address)

# Hash of a secret number that allows user
# to operate with funds from this contract.
secret_hash: public(bytes32)

# Assign owner to contract creator.
def __init__():
    self.owner = msg.sender

# This function allows to reset secret
# each secret should be used only once
# since everyone can track your transaction data
# in blockchain.
def set_secret(_secret: num, _new_secret: bytes32):
    # Only owner can execute this.
    assert msg.sender == self.owner

    # Prove ownership with a secret phrase.
    assert sha3(as_bytes32(_secret)) == self.secret_hash

    # Assign a new hash of the secret
    # pre-image of the hash is not known for third parties
    # since it was not stored in blockchain
    # until the first successful attempt to unlock this contract.
    self.secret_hash = _new_secret

# This function allows to deposit funds
# into this contract.
# `@payable` decorator allows function to receive Ether
@payable
def deposit():
    return

# A function that allows anyone
# to check which hash matches the entered secret.
# `@constant` decorator allows call this function
# without broadcasting a transaction to the blockchain.
@constant
def secret_from_num(_secret: num) -> bytes32:
    return sha3(as_bytes32(_secret))

# This function allows `owner` to withdraw funds
# if he will successfully prove ownership with a `secret`
def withdraw(_secret: num):

    # Prove ownership with a secret phrase.
    assert sha3(as_bytes32(_secret)) == self.secret_hash

    # Only owner can execute this.
    assert msg.sender == self.owner

    # Delivers funds from this contract to the `owner`
    # in case of successful unlocking of this contract.
    send(self.owner, self.balance)

    # NOTE: if the execution of this function was successful
    # then the execution data will remain in the blockchain
    # `secret` needs to be updated.

# Perform a call from this contract
# with given parameters.
def call(_to: address, _value: wei_value, _data: bytes <= 4096, _secret: num) -> bytes <= 4096:
    assert sha3(as_bytes32(_secret)) == self.secret_hash
    assert msg.sender == self.owner

    # Executes a raw call from this wallet
    # with the following parameters
    return raw_call(_to, _data, outsize=4096, gas=3000000, value=_value)
