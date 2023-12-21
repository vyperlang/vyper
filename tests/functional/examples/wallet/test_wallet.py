import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_keys import KeyAPI
from eth_utils import is_same_address


@pytest.fixture
def c(w3, get_contract):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    with open("examples/wallet/wallet.vy") as f:
        code = f.read()
    # Sends wei to the contract for future transactions gas costs
    c = get_contract(code, *[[a1, a2, a3, a4, a5], 3])
    w3.eth.send_transaction({"to": c.address, "value": 10**17})
    return c


@pytest.fixture
def sign(keccak):
    def _sign(seq, to, value, data, key):
        keys = KeyAPI()
        comb = seq.to_bytes(32, "big") + b"\x00" * 12 + to + value.to_bytes(32, "big") + data
        h1 = keccak(comb)
        h2 = keccak(b"\x19Ethereum Signed Message:\n32" + h1)
        sig = keys.ecdsa_sign(h2, key)
        return [28 if sig.v == 1 else 27, sig.r, sig.s]

    return _sign


def test_approve(w3, c, tester, tx_failed, sign):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    k0, k1, k2, k3, k4, k5, k6, k7 = tester.backend.account_keys[:8]

    to, value, data = b"\x35" * 20, 10**16, b""
    to_address = w3.to_checksum_address(to)

    def pack_and_sign(seq, *args):
        sigs = [sign(seq, to, value, data, k) if k else [0, 0, 0] for k in args]
        return sigs

    # Legitimate approval
    sigs = pack_and_sign(0, k1, 0, k3, 0, k5)
    c.approve(0, "0x" + to.hex(), value, data, sigs, transact={"value": value, "from": a1})
    # Approve fails if only 2 signatures are given
    sigs = pack_and_sign(1, k1, 0, k3, 0, 0)
    with tx_failed():
        c.approve(1, to_address, value, data, sigs, transact={"value": value, "from": a1})
    # Approve fails if an invalid signature is given
    sigs = pack_and_sign(1, k1, 0, k7, 0, k5)
    with tx_failed():
        c.approve(1, to_address, value, data, sigs, transact={"value": value, "from": a1})
    # Approve fails if transaction number is incorrect (the first argument should be 1)
    sigs = pack_and_sign(0, k1, 0, k3, 0, k5)
    with tx_failed():
        c.approve(0, to_address, value, data, sigs, transact={"value": value, "from": a1})
    # Approve fails if not enough value is sent
    sigs = pack_and_sign(1, k1, 0, k3, 0, k5)
    with tx_failed():
        c.approve(1, to_address, value, data, sigs, transact={"value": 0, "from": a1})
    sigs = pack_and_sign(1, k1, 0, k3, 0, k5)

    # this call should succeed
    c.approve(1, to_address, value, data, sigs, call={"value": value, "from": a1})

    print("Basic tests passed")


def test_javascript_signatures(w3, get_contract):
    a3 = w3.eth.accounts[2]
    # The zero address will cause `approve` to default to valid signatures
    zero_address = "0x0000000000000000000000000000000000000000"
    accounts = [
        "0x776ba14735ff84789320718cf0aa43e91f7a8ce1",
        "0x095ce4e4240fa66ff90282c26847456e3f3b5002",
    ]
    # The address that will receive the transaction
    recipient = "0x776Ba14735FF84789320718cf0aa43e91F7A8Ce1"
    # These are the matching sigs to the accounts
    raw_sigs = [
        "0x4a89507bf71749fb338ed13fba623a683d9ecab0fb9c389a4298525c043e38281a00ab65628bb18a382eb8c8b4fb4dae95ccc993cf49f617c60d8051180778601c",  # noqa: E501
        "0xc84fe5d2a600e033930e0cf73f26e78f4c65b134f9c9992f60f08ce0863abdbe0548a6e8aa2d952659f29c67106b59fdfcd64d67df03c1df620c70c85578ae701b",  # noqa: E501
    ]

    # Turns the raw sigs into sigs
    sigs = [
        (w3.to_int(x[64:]), w3.to_int(x[:32]), w3.to_int(x[32:64]))  # v  # r  # s
        for x in map(lambda z: w3.to_bytes(hexstr=z[2:]), raw_sigs)
    ]

    h = w3.keccak(
        (0).to_bytes(32, "big")
        + b"\x00" * 12
        + w3.to_bytes(hexstr=recipient[2:])
        + (25).to_bytes(32, "big")
        + b""
    )  # noqa: E501
    h2 = encode_defunct(h)

    # Check to make sure the signatures are valid
    assert is_same_address(Account.recover_message(h2, sigs[0]), accounts[0])
    assert is_same_address(Account.recover_message(h2, sigs[1]), accounts[1])

    # Set the owners to zero addresses
    with open("examples/wallet/wallet.vy") as f:
        owners = [w3.to_checksum_address(x) for x in accounts + [a3, zero_address, zero_address]]
        x2 = get_contract(f.read(), *[owners, 2])

    w3.eth.send_transaction({"to": x2.address, "value": 10**17})

    # There's no need to pass in signatures because the owners are 0 addresses
    # causing them to default to valid signatures
    x2.approve(
        0, recipient, 25, b"", sigs + [[0, 0, 0]] * 3, call={"to": x2.address, "value": 10**17}
    )

    print("Javascript signature tests passed")
