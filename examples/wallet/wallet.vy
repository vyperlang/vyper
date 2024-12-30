#pragma version >0.3.10

###########################################################################
## THIS IS EXAMPLE CODE, NOT MEANT TO BE USED IN PRODUCTION! CAVEAT EMPTOR!
###########################################################################

# An example of how you can implement a wallet in Vyper.

# A list of the owners addresses (there are a maximum of 5 owners)
owners: public(address[5])
# The number of owners required to approve a transaction
threshold: int128
# The number of transactions that have been approved
seq: public(int128)


@deploy
def __init__(_owners: address[5], _threshold: int128):
    for i: uint256 in range(5):
        if _owners[i] != empty(address):
            self.owners[i] = _owners[i]
    self.threshold = _threshold


@external
def testEcrecover(h: bytes32, v:uint8, r:bytes32, s:bytes32) -> address:
    return ecrecover(h, v, r, s)


# `@payable` allows functions to receive ether
@external
@payable
def approve(_seq: int128, to: address, _value: uint256, data: Bytes[4096], sigdata: uint256[3][5]) -> Bytes[4096]:
    # Throws if the value sent to the contract is less than the sum of the value to be sent
    assert msg.value >= _value
    # Every time the number of approvals starts at 0 (multiple signatures can be added through the sigdata argument)
    approvals: int128 = 0
    # Starts by combining:
    # 1) The number of transactions approved thus far.
    # 2) The address the transaction is going to be sent to (can be a contract or a user).
    # 3) The value in wei that will be sent with this transaction.
    # 4) The data to be sent with this transaction (usually data is used to deploy contracts or to call functions on contracts, but you can put whatever you want in it).
    # Takes the keccak256 hash of the combination
    h: bytes32 = keccak256(concat(convert(_seq, bytes32), convert(to, bytes32), convert(_value, bytes32), data))
    # Then we combine the Ethereum Signed message with our previous hash
    # Owners will have to sign the below message
    h2: bytes32 = keccak256(concat(b"\x19Ethereum Signed Message:\n32", h))
    # Verifies that the caller of approve has entered the correct transaction number
    assert self.seq == _seq
    # # Iterates through all the owners and verifies that there signatures,
    # # given as the sigdata argument are correct
    for i: uint256 in range(5):
        if sigdata[i][0] != 0:
            # If an invalid signature is given for an owner then the contract throws
            assert ecrecover(h2, sigdata[i][0], sigdata[i][1], sigdata[i][2]) == self.owners[i]
            # ecrecover handles multiple types
            assert ecrecover(h2, convert(sigdata[i][0], uint8), convert(sigdata[i][1], bytes32), convert(sigdata[i][2], bytes32)) == self.owners[i]
            # For every valid signature increase the number of approvals by 1
            approvals += 1
    # Throw if the number of approvals is less then the number of approvals required (the threshold)
    assert approvals >= self.threshold
    # The transaction has been approved
    # Increase the number of approved transactions by 1
    self.seq += 1
    # Use raw_call to send the transaction
    return raw_call(to, data, max_outsize=4096, gas=3000000, value=_value)


@external
@payable
def __default__():
    pass
