from ethereum.tools import tester as t
from ethereum import utils
c = t.Chain()
c.head_state.gas_limit = 10**9

x = c.contract(open('wallet.v.py').read(), args=[[t.a1, t.a2, t.a3, t.a4, t.a5], 3], language='viper')
print(c.last_tx.data[-192:])
c.tx(sender=t.k1, to=x.address, value=10**17)

print([utils.encode_hex(a) for a in [t.a1, t.a2, t.a3, t.a4, t.a5]])

def sign(seq, to, value, data, key):
    h1 = utils.sha3(utils.encode_int32(seq) + b'\x00' * 12 + to + utils.encode_int32(value) + data)
    h2 = utils.sha3(b"\x19Ethereum Signed Message:\n32" + h1)
    return list(utils.ecsign(h2, key))

to, value, data = b'\x35' * 20, 10**16, b""

assert x.approve(0, to, value, data, [sign(0, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)])

try:
    x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, 0, 0, t.k5)])
    success = True
except:
    success = False

assert not success

try:
    x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k7, 0, t.k5)])
    success = True
except:
    success = False

assert not success

try:
    assert x.approve(0, to, value, data, [sign(0, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)])
    success = True
except:
    success = False

assert not success

assert x.approve(1, to, value, data, [sign(1, to, value, data, k) if k else [0, 0, 0] for k in (t.k1, 0, t.k3, 0, t.k5)])

print("Basic tests passed")

zero_address = "0x0000000000000000000000000000000000000000"
accounts = ["0x776ba14735ff84789320718cf0aa43e91f7a8ce1", "0x095ce4e4240fa66ff90282c26847456e3f3b5002"]
recipient = "0x776ba14735ff84789320718cf0aa43e91f7a8ce1"
raw_sigs = [
    "0x4a89507bf71749fb338ed13fba623a683d9ecab0fb9c389a4298525c043e38281a00ab65628bb18a382eb8c8b4fb4dae95ccc993cf49f617c60d8051180778601c",
    "0xc84fe5d2a600e033930e0cf73f26e78f4c65b134f9c9992f60f08ce0863abdbe0548a6e8aa2d952659f29c67106b59fdfcd64d67df03c1df620c70c85578ae701b"
]
sigs = [(utils.big_endian_to_int(x[64:]), utils.big_endian_to_int(x[:32]), utils.big_endian_to_int(x[32:64])) for x in 
        map(lambda z: utils.decode_hex(z[2:]), raw_sigs)]

h = utils.sha3(utils.encode_int32(0) + b'\x00' * 12 + utils.decode_hex(recipient[2:]) + utils.encode_int32(25) + b'')
h2 = utils.sha3(b"\x19Ethereum Signed Message:\n32" + h)

assert '0x'+utils.encode_hex(utils.sha3(utils.ecrecover_to_pub(h2, sigs[0][0], sigs[0][1], sigs[0][2]))[12:]) == accounts[0]
assert '0x'+utils.encode_hex(utils.sha3(utils.ecrecover_to_pub(h2, sigs[1][0], sigs[1][1], sigs[1][2]))[12:]) == accounts[1]

x2 = c.contract(open('wallet.v.py').read(), args=[accounts + [t.a3, zero_address, zero_address], 2], language='viper')
c.tx(sender=t.k1, to=x2.address, value=10**17)

assert x2.approve(0, recipient, 25, "", sigs + [[0, 0, 0]] * 3)

print("Javascript signature tests passed")
