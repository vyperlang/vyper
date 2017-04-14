from ethereum import transactions, utils
import serpent
import rlp
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'

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
t.gas_limit = 1000000
s = t.state()
c = s.evm(rlp_decoder, sender=t.k0, endowment=0)
assert s.send(t.k0, c, 0, rlp.encode([b'\x45', b'\x95'])) == encode_vals([96, 129, 162, 1, b"\x45", 1, b"\x95"])
assert s.send(t.k0, c, 0, rlp.encode([b'cow', b'dog'])) == encode_vals([96, 131, 166, 3, b"cow", 3, b"dog"])
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
print("500 bytes increment: %d" % (g2 - g1))
print("500 bytes increment: %d" % (g4 - g3))
print("25 items increment: %d" % (g3 - g1))
print("25 items increment: %d" % (g4 - g2))

# configure_logging(config_string=config_string)
s.send(t.k0, c, 0, b'\xf8\xc7\x01\xa055555555555555555555555555555555\xa0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x80\xa0\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xb8`\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1b\x88\xa7\x85r\x1b3\x17\xcaP\x96\xca\xd3S\xfcgM\xec\xe0\xf5!\xc8\xb4m\xd9\xb7E\xf3\x81d\x87\x93VD\xe0Ej\xcd\xec\x80\x11\x86(qZ\x9b\x80\xbf\xce\xe5*\r\x9d.o\xcd\x11s\xc5\xbc\x8c\xcb\xb9\xa9 ')
g = s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used
print("Casper prepare: %d" % g)


# Create transaction

t = transactions.Transaction(0, 30 * 10**9, 2999999, '', 0, rlp_decoder)
t.startgas = t.intrinsic_gas_used + 50000 + 200 * len(rlp_decoder)
t.v = 27
t.r = 45
t.s = 79
print("RLP decoder")
print("Instructions for launching:")
print('First send %d wei to %s' % (t.startgas * t.gasprice,
                             utils.checksum_encode(t.sender)))
print('Publish this tx to create the contract: 0x'+utils.encode_hex(rlp.encode(t)))
print('This is the contract address: '+utils.checksum_encode(utils.mk_contract_address(t.sender, 0)))
