from ethereum import transactions, utils
import serpent
import rlp

rlp_decoder = serpent.compile('rlp_decoder.se.py')

def encode_vals(vals):
    o = b''
    for v in vals:
        if isinstance(v, int):
            o += utils.encode_int32(v)
        else:
            o += v
    return o

# Run some tests first

from ethereum import tester as t
s = t.state()
c = s.evm(rlp_decoder, sender=t.k0, endowment=0)
assert s.send(t.k0, c, 0, rlp.encode([b'\x45', b'\x95'])) == encode_vals([96, 129, 162, 1, b"\x45", 1, b"\x95"])
assert s.send(t.k0, c, 0, rlp.encode([b'cow', b'dog'])) == encode_vals([96, 131, 166, 3, b"cow", 3, b"dog"])
assert s.send(t.k0, c, 0, rlp.encode([])) == encode_vals([32])
assert s.send(t.k0, c, 0, rlp.encode([b'\x73' * 100, b'dog'])) == encode_vals([96, 228, 263, 100, b"\x73" * 100, 3, b"dog"])
assert s.send(t.k0, c, 0, utils.decode_hex('f6943535353535353535353535353535353535353535a04747474747474747474747474747474747474747474747474747474747474747')) == encode_vals([96, 148, 212, 20, b'\x35' * 20, 32, b'\x47' * 32])
print("Checks passed!")

s.send(t.k0, c, 0, rlp.encode([]))
g1 = s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used
s.send(t.k0, c, 0, rlp.encode([b'\x03' * 500]))
g2 = s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used
s.send(t.k0, c, 0, rlp.encode([b'\x03'] * 25))
g3 = s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used
s.send(t.k0, c, 0, rlp.encode([b'\x03'] * 24 + [b'\x03' * 500]))
g4 = s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used
#print("500 bytes: %d" % (g2 - g1))
#print("500 bytes: %d" % (g4 - g3))
#print("25 items: %d" % (g3 - g1))
#print("25 items: %d" % (g4 - g2))

# Create transaction

t = transactions.Transaction(0, 30 * 10**9, 2999999, '', 0, rlp_decoder)
t.startgas = t.intrinsic_gas_used + 50000 + 200 * len(rlp_decoder)
t.v = 27
t.r = 45
t.s = 79
print("RLP decoder")
print('Send %d wei to %s' % (t.startgas * t.gasprice,
                             '0x'+utils.encode_hex(t.sender)))
print('Contract address: 0x'+utils.encode_hex(utils.mk_contract_address(t.sender, 0)))
print('Code: 0x'+utils.encode_hex(rlp.encode(t)))
