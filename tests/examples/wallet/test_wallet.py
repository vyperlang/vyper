import pytest


@pytest.fixture
def c(w3, tester, get_contract):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    with open('examples/wallet/wallet.v.py') as f:
        code = f.read()
    # Sends wei to the contract for future transactions gas costs
    import ipdb; ipdb.set_trace()
    return get_contract(code, *[[a1, a2, a3, a4, a5], 3], value=10**17)

# Signs a transaction with a given key
# @pytest.fixture
# def sign():
#     def _sign(seq, to, value, data, key):
#         from web3 import Web3
#         from eth_account.messages import defunct_hash_message
#         h1 = Web3.sha3(utils.encode_int32(seq) + b'\x00' * 12 + to + utils.encode_int32(value) + data)
#         h2 = Web3.sha3(b"\x19Ethereum Signed Message:\n32" + h1)
#         import ipdb; ipdb.set_trace()
#         return list(utils.ecsign(h2, key))
#     return _sign


def test_approve(w3, c, assert_tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    to, value, data = b'\x35' * 20, 10**16, b""
    import ipdb; ipdb.set_trace()
    assert c.approve(0, to, value, data, [sign(0, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)], value=value, sender=t.k1)

    # Approve fails if only 2 signatures are given
    assert_tx_failed(lambda: x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, 0, 0, t.k5)], value=value, sender=t.k1))
    # Approve fails if an invalid signature is given
    assert_tx_failed(lambda: x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k7, 0, t.k5)], value=value, sender=t.k1))
    # Approve fails if transaction number is incorrect (the first argument should be 1)
    assert_tx_failed(lambda: x.approve(0, to, value, data, [sign(0, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)], value=value, sender=t.k1))
    # Approve fails if not enough value is sent
    assert_tx_failed(lambda: x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)], value=0, sender=t.k1))
    assert x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)], value=value, sender=t.k1)
    print("Basic tests passed")


def test_javascript_signatures():
    # The zero address will cause `approve` to default to valid signatures
    zero_address = "0x0000000000000000000000000000000000000000"
    accounts = ["0x776ba14735ff84789320718cf0aa43e91f7a8ce1", "0x095ce4e4240fa66ff90282c26847456e3f3b5002"]
    # The address that will receive the transaction
    recipient = "0x776ba14735ff84789320718cf0aa43e91f7a8ce1"
    # These are the matching sigs to the accounts
    raw_sigs = [
        "0x4a89507bf71749fb338ed13fba623a683d9ecab0fb9c389a4298525c043e38281a00ab65628bb18a382eb8c8b4fb4dae95ccc993cf49f617c60d8051180778601c",
        "0xc84fe5d2a600e033930e0cf73f26e78f4c65b134f9c9992f60f08ce0863abdbe0548a6e8aa2d952659f29c67106b59fdfcd64d67df03c1df620c70c85578ae701b"
    ]

    # Turns the raw sigs into sigs
    sigs = [(utils.big_endian_to_int(x[64:]), utils.big_endian_to_int(x[:32]), utils.big_endian_to_int(x[32:64])) for x in
            map(lambda z: utils.decode_hex(z[2:]), raw_sigs)]

    h = utils.sha3(utils.encode_int32(0) + b'\x00' * 12 + utils.decode_hex(recipient[2:]) + utils.encode_int32(25) + b'')
    h2 = utils.sha3(b"\x19Ethereum Signed Message:\n32" + h)
    # Check to make sure the signatures are valid
    assert '0x' + utils.encode_hex(utils.sha3(utils.ecrecover_to_pub(h2, sigs[0][0], sigs[0][1], sigs[0][2]))[12:]) == accounts[0]
    assert '0x' + utils.encode_hex(utils.sha3(utils.ecrecover_to_pub(h2, sigs[1][0], sigs[1][1], sigs[1][2]))[12:]) == accounts[1]

    # Set the owners to zero addresses
    x2 = t.s.contract(open('examples/wallet/wallet.v.py').read(), args=[accounts + [t.a3, zero_address, zero_address], 2], language='vyper')
    t.s.tx(sender=t.k1, to=x2.address, value=10**17)

    # There's no need to pass in signatures because the owners are 0 addresses causing them to default to valid signatures
    assert x2.approve(0, recipient, 25, "", sigs + [[0, 0, 0]] * 3, value=25, sender=t.k1)

    print("Javascript signature tests passed")
