# An example of how you can do a wallet in Viper.
# Warning: NOT AUDITED. Do not use to store substantial quantities of funds.

# A list of the owners addresses (there are a maximum of 5 owners)
owners: address[5]
# The number of owners required to approve a transaction
threshold: num
# The number of transactions that have been approved
seq: num

@public
def __init__(_owners: address[5], _threshold: num):
    for i in range(5):
        if _owners[i]:
            self.owners[i] = _owners[i]
    self.threshold = _threshold

# `@payable` allows functions to receive ether
@public
@payable
def approve(_seq: num, to: address, value: wei_value, data: bytes <= 4096, sigdata: num256[3][5]) -> bytes <= 4096:
    # Throws if the value sent to the contract is less than the sum of the value to be sent
    assert msg.value >= value
    # Every time the number of approvals starts at 0 (multiple signatures can be added through the sigdata argument)
    approvals:num = 0
    # Starts by combining:
    # 1) The number of transactions approved thus far.
    # 2) The address the transaction is going to be sent to (can be a contract or a user).
    # 3) The value in wei that will be sent with this transaction.
    # 4) The data to be sent with this transaction (usually data is used to deploy contracts or to call functions on contracts, but you can put whatever you want in it).
    # Takes the sha3 (keccak256) hash of the combination
    h: bytes32 = sha3(concat(as_bytes32(_seq), as_bytes32(to), as_bytes32(value), data))
    # Then we combine the Ethereum Signed message with our previous hash
    # Owners will have to sign the below message
    h2: bytes32 = sha3(concat("\x19Ethereum Signed Message:\n32", h))
    # Verifies that the caller of approve has entered the correct transaction number
    assert self.seq == _seq
    # Iterates through all the owners and verifies that there signatures,
    # given as the sigdata argument are correct
    for i in range(5):
        if sigdata[i][0]:
            # If an invalid signature is given for an owner then the contract throws
            assert ecrecover(h2, sigdata[i][0], sigdata[i][1], sigdata[i][2]) == self.owners[i]
            # For every valid signature increase the number of approvals by 1
            approvals += 1
    # Throw if the number of approvals is less then the number of approvals required (the threshold)
    assert approvals >= self.threshold
    # The transaction has been approved
    # Increase the number of approved transactions by 1
    self.seq += 1
    # Use raw_call to send the transaction
    return raw_call(to, data, outsize=4096, gas=3000000, value=value)
