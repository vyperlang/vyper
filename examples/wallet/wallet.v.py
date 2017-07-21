# An example of how you can do a wallet in Viper.
# Warning: NOT AUDITED. Do not use to store substantial quantities of funds.

addrs: address[5]
threshold: num
seq: num

def __init__(_addrs: address[5], _threshold: num):
    for i in range(5):
        if _addrs[i]:
            self.addrs[i] = _addrs[i]
    self.threshold = _threshold

def approve(_seq: num, to: address, value: wei_value, data: bytes <= 4096, sigdata: num256[3][5]) -> bytes <= 4096:
    approvals = 0
    h = sha3(concat(as_bytes32(_seq), as_bytes32(to), as_bytes32(value), data))
    h2 = sha3(concat("\x19Ethereum Signed Message:\n32", h))
    assert self.seq == _seq
    for i in range(5):
        if sigdata[i][0]:
            assert ecrecover(h2, sigdata[i][0], sigdata[i][1], sigdata[i][2]) == self.addrs[i]
            approvals += 1
    assert approvals >= self.threshold
    self.seq += 1
    return raw_call(to, data, outsize=4096, gas=3000000, value=value)
