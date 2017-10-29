from ethereum import transactions, utils
import rlp
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
from viper import optimizer, compile_lll
from rlp_decoder import rlp_decoder_bytes

def encode_vals(vals):
    o = b''
    for v in vals:
        if isinstance(v, int):
            o += utils.encode_int32(v)
        else:
            o += v
    return o

# Run some tests first

from ethereum.tools import tester as t
t.gas_limit = 1000000
chain = t.Chain()
t.s = chain

rlp_decoder_address = t.s.tx(to=b'', data=rlp_decoder_bytes)
assert t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'\x45', b'\x95'])) == encode_vals([96, 129, 162, 1, b"\x45", 1, b"\x95"])
assert t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'cow', b'dog']))== encode_vals([96, 131, 166, 3, b"cow", 3, b"dog"])
assert t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([]))== encode_vals([32])
assert t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'\x73' * 100, b'dog']))== encode_vals([96, 228, 263, 100, b"\x73" * 100, 3, b"dog"])
assert t.s.tx(sender=t.k0, to=rlp_decoder_address, data=utils.decode_hex('f6943535353535353535353535353535353535353535a04747474747474747474747474747474747474747474747474747474747474747'))== encode_vals([96, 148, 212, 20, b'\x35' * 20, 32, b'\x47' * 32])
print("Checks passed!")

t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([]))
g1 = t.s.head_state.receipts[-1].gas_used - t.s.head_state.receipts[-2].gas_used - t.s.last_tx.intrinsic_gas_used
t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'\x03' * 500]))
g2 = t.s.head_state.receipts[-1].gas_used - t.s.head_state.receipts[-2].gas_used - t.s.last_tx.intrinsic_gas_used
t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'\x03'] * 25))
g3 = t.s.head_state.receipts[-1].gas_used - t.s.head_state.receipts[-2].gas_used - t.s.last_tx.intrinsic_gas_used
t.s.tx(sender=t.k0, to=rlp_decoder_address, data=rlp.encode([b'\x03'] * 24 + [b'\x03' * 500]))
g4 = t.s.head_state.receipts[-1].gas_used - t.s.head_state.receipts[-2].gas_used - t.s.last_tx.intrinsic_gas_used

print("500 bytes increment: %d" % (g2 - g1))
print("500 bytes increment: %d" % (g4 - g3))
print("25 items increment: %d" % (g3 - g1))
print("25 items increment: %d" % (g4 - g2))


# Create transaction
t = transactions.Transaction(0, 30 * 10**9, 2999999, '', 0, rlp_decoder_bytes)
t.startgas = t.intrinsic_gas_used + 50000 + 200 * len(rlp_decoder_bytes)
t.v = 27
t.r = 45
t.s = 79
print("RLP decoder")
print("Instructions for launching:")
print('First send %d wei to %s' % (t.startgas * t.gasprice,
                             utils.checksum_encode(t.sender)))
print('Publish this tx to create the contract: 0x'+utils.encode_hex(rlp.encode(t)))
print('This is the contract address: '+utils.checksum_encode(utils.mk_contract_address(t.sender, 0)))
