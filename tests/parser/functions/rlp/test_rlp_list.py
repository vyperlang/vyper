import rlp


def test_rlp_decoder_code(w3, assert_tx_failed, get_contract_with_gas_estimation, fake_tx):
    fake_tx()

    rlp_decoder_code = """
u: bytes[100]

@public
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[0]

@public
def fop() -> bytes32:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]

@public
def foq() -> bytes[100]:
    x = RLPList('\xc5\x83cow\x03', [bytes, int128])
    return x[0]

@public
def fos() -> int128:
    x = RLPList('\xc5\x83cow\x03', [bytes, int128])
    return x[1]

@public
def fot() -> uint256:
    x = RLPList('\xc5\x83cow\x03', [bytes, uint256])
    return x[1]

@public
def qoo(inp: bytes[100]) -> address:
    x = RLPList(inp, [address, bytes32])
    return x[0]

@public
def qos(inp: bytes[100]) -> int128:
    x = RLPList(inp, [int128, int128])
    return x[0] + x[1]

@public
def qot(inp: bytes[100]):
    x = RLPList(inp, [int128, int128])

@public
def qov(inp: bytes[100]) -> (uint256, uint256):
    x = RLPList(inp, [uint256, uint256])
    return x[0], x[1]

@public
def roo(inp: bytes[100]) -> address:
    self.u = inp
    x = RLPList(self.u, [address, bytes32])
    return x[0]

@public
def too(inp: bytes[100]) -> bool:
    x = RLPList(inp, [bool])
    return x[0]

@public
def voo(inp: bytes[1024]) -> int128:
    x = RLPList(inp, [int128, int128, bytes32, int128, bytes32, bytes])
    return x[1]

@public
def loo(inp: bytes[1024]) -> int128:
    x = RLPList(inp, [int128, int128, int128, int128, int128, int128, int128, int128, int128, int128])
    return x[0] + x[1] + x[2] + x[3] + x[4] + x[5] + x[6] + x[7] + x[8] + x[9]

@public
def woo(inp: bytes[1024]) -> bytes[15360]:
    x = RLPList(inp, [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return concat(x[0], x[1], x[2], x[3], x[4], x[5], x[6], x[7], x[8], x[9], x[10], x[11], x[12], x[13], x[14])

@public
def yolo(raw_utxo: bytes[1024]) -> (address, int128, int128):
    utxo = RLPList(raw_utxo, [address, int128, int128])
    return utxo[0], utxo[1], utxo[2]
    """
    c = get_contract_with_gas_estimation(rlp_decoder_code)

    assert c.foo() == '0x' + '35' * 20
    assert c.fop() == b'G' * 32
    assert c.foq() == b'cow'
    assert c.fos() == 3
    assert c.fot() == 3
    assert c.qoo(b'\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG') == '0x' + '35' * 20
    assert c.roo(b'\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG') == '0x' + '35' * 20
    assert c.qos(rlp.encode([3, 30])) == 33
    assert c.qos(rlp.encode([3, 2**100 - 5])) == 2**100 - 2
    assert c.voo(rlp.encode([b'', b'\x01', b'\xbds\xc31\xf5=b\xa5\xcfy]\x0f\x05\x8f}\\\xf3\xe6\xea\x9d~\r\x96\xda\xdf:+\xdb4pm\xcc', b'', b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00', b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1b:\xcd\x85\x9b\x84`FD\xf9\xa8'\x8ezR\xd5\xc9*\xf5W\x1f\x14\xc2\x0cd\xa0\x17\xd4Z\xde\x9d\xc2\x18_\x82B\xc2\xaa\x82\x19P\xdd\xa2\xd0\xe9(\xcaO\xe2\xb1\x13s\x05yS\xc3q\xdb\x1eB\xe2g\xaa'\xba"])) == 1
    assert_tx_failed(lambda: c.qot(rlp.encode([7, 2**160])))
    c.qov(rlp.encode([7, 2**160]))
    assert_tx_failed(lambda: c.qov(rlp.encode([2**160])))
    assert c.qov(rlp.encode([b'\x03', b'\x00\x01'])) == [3, 1]
    c.qov(rlp.encode([b'\x03', b'\x01']))
    assert c.qov(rlp.encode([b'\x03', b'\x04'])) == [3, 4]
    assert c.qov(rlp.encode([b'\x03', b'\x00'])) == [3, 0]
    assert c.too(rlp.encode([b'\x01'])) is True
    assert c.too(rlp.encode([b''])) is False
    assert_tx_failed(lambda: c.too(rlp.encode([b'\x02'])))
    assert_tx_failed(lambda: c.too(rlp.encode([b'\x00'])))
    assert c.loo(rlp.encode([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])) == 55
    assert c.woo(rlp.encode([b'1', b'2', b'3', b'4', b'5', b'6', b'7', b'8', b'9', b'10', b'11', b'12', b'13', b'14', b'15'])) == b'123456789101112131415'
    assert c.yolo(rlp.encode([w3.toBytes(hexstr=w3.eth.accounts[0]), 1, 2])) == [w3.eth.accounts[0], 1, 2]
    print('Passed RLP decoder tests')
