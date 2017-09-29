import pytest
from .setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, G1, G1_times_two, G1_times_three, \
    curve_order, negative_G1


def test_block_number():
    block_number_code = """
def block_number() -> num:
    return block.number
"""
    c = get_contract(block_number_code)
    c.block_number() == 2


def test_send():
    send_test = """

def foo():
    send(msg.sender, self.balance+1)

def fop():
    send(msg.sender, 10)
    """
    c = s.contract(send_test, language='viper', value=10)
    with pytest.raises(t.TransactionFailed):
        c.foo()
    c.fop()
    with pytest.raises(t.TransactionFailed):
        c.fop()


def test_init_argument_test():
    init_argument_test = """
moose: num
def __init__(_moose: num):
    self.moose = _moose

def returnMoose() -> num:
    return self.moose
    """

    c = get_contract_with_gas_estimation(init_argument_test, args=[5])
    assert c.returnMoose() == 5
    print('Passed init argument test')


def test_constructor_advanced_code():
    constructor_advanced_code = """
twox: num

def __init__(x: num):
    self.twox = x * 2

def get_twox() -> num:
    return self.twox
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code, args=[5])
    assert c.get_twox() == 10


def test_constructor_advanced_code2():
    constructor_advanced_code2 = """
comb: num

def __init__(x: num[2], y: bytes <= 3, z: num):
    self.comb = x[0] * 1000 + x[1] * 100 + len(y) * 10 + z

def get_comb() -> num:
    return self.comb
    """
    c = get_contract_with_gas_estimation(constructor_advanced_code2, args=[[5,7], "dog", 8])
    assert c.get_comb() == 5738
    print("Passed advanced init argument tests")

def test_permanent_variables_test():
    permanent_variables_test = """
var: {a: num, b: num}
def __init__(a: num, b: num):
    self.var.a = a
    self.var.b = b

def returnMoose() -> num:
    return self.var.a * 10 + self.var.b
    """

    c = get_contract_with_gas_estimation(permanent_variables_test, args=[5, 7])
    assert c.returnMoose() == 57
    print('Passed init argument and variable member test')


def test_packing_test():
    packing_test = """
x: num
y: num[5]
z: {foo: num[3], bar: {a: num, b: num}[2]}
a: num

def foo() -> num:
    self.x = 1
    self.y[0] = 2
    self.y[4] = 4
    self.z.foo[0] = 8
    self.z.foo[2] = 16
    self.z.bar[0].a = 32
    self.z.bar[0].b = 64
    self.z.bar[1].a = 128
    self.z.bar[1].b = 256
    self.a = 512
    return self.x + self.y[0] + self.y[4] + self.z.foo[0] + self.z.foo[2] + \
        self.z.bar[0].a + self.z.bar[0].b + self.z.bar[1].a + self.z.bar[1].b + self.a

def fop() -> num:
    _x: num
    _y: num[5]
    _z: {foo: num[3], bar: {a: num, b: num}[2]}
    _a: num
    _x = 1
    _y[0] = 2
    _y[4] = 4
    _z.foo[0] = 8
    _z.foo[2] = 16
    _z.bar[0].a = 32
    _z.bar[0].b = 64
    _z.bar[1].a = 128
    _z.bar[1].b = 256
    _a = 512
    return _x + _y[0] + _y[4] + _z.foo[0] + _z.foo[2] + \
        _z.bar[0].a + _z.bar[0].b + _z.bar[1].a + _z.bar[1].b + _a
    """

    c = get_contract_with_gas_estimation(packing_test)
    assert c.foo() == 1023, c.foo()
    assert c.fop() == 1023, c.fop()
    print('Passed packing test')


def test_test_slice():
    test_slice = """
def foo(inp1: bytes <= 10) -> bytes <= 3:
    x = 5
    s = slice(inp1, start=3, len=3)
    y = 7
    return s

def bar(inp1: bytes <= 10) -> num:
    x = 5
    s = slice(inp1, start=3, len=3)
    y = 7
    return x * y
    """

    c = get_contract(test_slice)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35

    print('Passed slice test')


def test_test_slice2():
    test_slice2 = """
def slice_tower_test(inp1: bytes <= 50) -> bytes <= 50:
    inp = inp1
    for i in range(1, 11):
        inp = slice(inp, start=1, len=30 - i * 2)
    return inp
    """

    c = get_contract_with_gas_estimation(test_slice2)
    x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
    assert x == b"klmnopqrst", x

    print('Passed advanced slice test')


def test_test_slice3():
    test_slice3 = """
x: num
s: bytes <= 50
y: num
def foo(inp1: bytes <= 50) -> bytes <= 50:
    self.x = 5
    self.s = slice(inp1, start=3, len=3)
    self.y = 7
    return self.s

def bar(inp1: bytes <= 50) -> num:
    self.x = 5
    self.s = slice(inp1, start=3, len=3)
    self.y = 7
    return self.x * self.y
    """

    c = get_contract(test_slice3)
    x = c.foo(b"badminton")
    assert x == b"min", x

    assert c.bar(b"badminton") == 35

    print('Passed storage slice test')


def test_test_slice4():
    test_slice4 = """
def foo(inp: bytes <= 10, start: num, len: num) -> bytes <= 10:
    return slice(inp, start=start, len=len)
    """

    c = get_contract(test_slice4)
    assert c.foo(b"badminton", 3, 3) == b"min"
    assert c.foo(b"badminton", 0, 9) == b"badminton"
    assert c.foo(b"badminton", 1, 8) == b"adminton"
    assert c.foo(b"badminton", 1, 7) == b"adminto"
    assert c.foo(b"badminton", 1, 0) == b""
    assert c.foo(b"badminton", 9, 0) == b""
    try:
        c.foo(b"badminton", 0, 10)
        assert False
    except:
        pass
    try:
        c.foo(b"badminton", 1, 9)
        assert False
    except:
        pass
    try:
        c.foo(b"badminton", 9, 1)
        assert False
    except:
        pass
    try:
        c.foo(b"badminton", 10, 0)
        assert False
    except:
        pass

    print('Passed slice edge case test')


def test_test_length():
    test_length = """
y: bytes <= 10
def foo(inp: bytes <= 10) -> num:
    x = slice(inp, start=1, len=5)
    self.y = slice(inp, start=2, len=4)
    return len(inp) * 100 + len(x) * 10 + len(self.y)
    """

    c = get_contract(test_length)
    assert c.foo(b"badminton") == 954, c.foo(b"badminton")
    print('Passed length test')


def test_test_concat():
    test_concat = """
def foo2(input1: bytes <= 50, input2: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2)

def foo3(input1: bytes <= 50, input2: bytes <= 50, input3: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2, input3)
    """

    c = get_contract(test_concat)
    assert c.foo2(b"h", b"orse") == b"horse"
    assert c.foo2(b"h", b"") == b"h"
    assert c.foo2(b"", b"") == b""
    assert c.foo2(b"", b"orse") == b"orse"
    assert c.foo3(b"Buffalo", b" ", b"buffalo") == b"Buffalo buffalo"
    assert c.foo2(b"\x36", b"\x35" * 32) == b"\x36" + b"\x35" * 32
    assert c.foo2(b"\x36" * 48, b"\x35" * 32) == b"\x36" * 48 + b"\x35" * 32
    assert c.foo3(b"horses" * 4, b"mice" * 7, b"crows" * 10) == b"horses" * 4 + b"mice" * 7 + b"crows" * 10
    print('Passed simple concat test')


def test_test_concat2():
    test_concat2 = """
def foo(inp: bytes <= 50) -> bytes <= 1000:
    x = inp
    return concat(x, inp, x, inp, x, inp, x, inp, x, inp)
    """

    c = get_contract(test_concat2)
    assert c.foo(b"horse" * 9 + b"viper") == (b"horse" * 9 + b"viper") * 10
    print('Passed second concat test')


def test_crazy_concat_code():
    crazy_concat_code = """
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 25:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
    """

    c = get_contract(crazy_concat_code)

    assert c.krazykonkat(b"moose") == b'cow horse moose'

    print('Passed third concat test')


def test_hash_code():
    hash_code = """
def foo(inp: bytes <= 100) -> bytes32:
    return sha3(inp)

def bar() -> bytes32:
    return sha3("inp")
    """

    c = get_contract(hash_code)
    for inp in (b"", b"cow", b"s" * 31, b"\xff" * 32, b"\n" * 33, b"g" * 64, b"h" * 65):
        assert c.foo(inp) == u.sha3(inp)

    assert c.bar() == u.sha3("inp")


def test_hash_code2():
    hash_code2 = """
def foo(inp: bytes <= 100) -> bool:
    return sha3(inp) == sha3("badminton")
    """
    c = get_contract(hash_code2)
    assert c.foo(b"badminto") is False
    assert c.foo(b"badminton") is True


def test_hash_code3():
    hash_code3 = """
test: bytes <= 100
def set_test(inp: bytes <= 100):
    self.test = inp

def tryy(inp: bytes <= 100) -> bool:
    return sha3(inp) == sha3(self.test)

def trymem(inp: bytes <= 100) -> bool:
    x = self.test
    return sha3(inp) == sha3(x)

def try32(inp: bytes32) -> bool:
    return sha3(inp) == sha3(self.test)
    """
    c = get_contract(hash_code3)
    c.set_test(b"")
    assert c.tryy(b"") is True
    assert c.trymem(b"") is True
    assert c.tryy(b"cow") is False
    c.set_test(b"cow")
    assert c.tryy(b"") is False
    assert c.tryy(b"cow") is True
    c.set_test(b"\x35" * 32)
    assert c.tryy(b"\x35" * 32) is True
    assert c.trymem(b"\x35" * 32) is True
    assert c.try32(b"\x35" * 32) is True
    assert c.tryy(b"\x35" * 33) is False
    c.set_test(b"\x35" * 33)
    assert c.tryy(b"\x35" * 32) is False
    assert c.trymem(b"\x35" * 32) is False
    assert c.try32(b"\x35" * 32) is False
    assert c.tryy(b"\x35" * 33) is True

    print("Passed SHA3 hash test")


def test_method_id_test():
    method_id_test = """
def double(x: num) -> num:
    return x * 2

def returnten() -> num:
    ans = raw_call(self, concat(method_id("double(int128)"), as_bytes32(5)), gas=50000, outsize=32)
    return as_num128(extract32(ans, 0))
    """
    c = get_contract(method_id_test)
    assert c.returnten() == 10
    print("Passed method ID test")


def test_ecrecover_test():
    ecrecover_test = """
def test_ecrecover(h: bytes32, v:num256, r:num256, s:num256) -> address:
    return ecrecover(h, v, r, s)

def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     as_num256(28),
                     as_num256(63198938615202175987747926399054383453528475999185923188997970550032613358815),
                     as_num256(6577251522710269046055727877571505144084475024240851440410274049870970796685))
    """

    c = get_contract(ecrecover_test)
    h = b'\x35' * 32
    k = b'\x46' * 32
    v, r, S = u.ecsign(h, k)
    assert c.test_ecrecover(h, v, r, S) == '0x' + u.encode_hex(u.privtoaddr(k))
    assert c.test_ecrecover2() == '0x' + u.encode_hex(u.privtoaddr(k))

    print("Passed ecrecover test")


def test_extract32_code():
    extract32_code = """
y: bytes <= 100
def extrakt32(inp: bytes <= 100, index: num) -> bytes32:
    return extract32(inp, index)

def extrakt32_mem(inp: bytes <= 100, index: num) -> bytes32:
    x = inp
    return extract32(x, index)

def extrakt32_storage(index: num, inp: bytes <= 100) -> bytes32:
    self.y = inp
    return extract32(self.y, index)
    """

    c = get_contract_with_gas_estimation(extract32_code)
    test_cases = (
        (b"c" * 31, 0),
        (b"c" * 32, 0),
        (b"c" * 32, -1),
        (b"c" * 33, 0),
        (b"c" * 33, 1),
        (b"c" * 33, 2),
        (b"cow" * 30, 0),
        (b"cow" * 30, 1),
        (b"cow" * 30, 31),
        (b"cow" * 30, 32),
        (b"cow" * 30, 33),
        (b"cow" * 30, 34),
        (b"cow" * 30, 58),
        (b"cow" * 30, 59),
    )

    for S, i in test_cases:
        expected_result = S[i: i + 32] if 0 <= i <= len(S) - 32 else None
        if expected_result is None:
            try:
                o = c.extrakt32(S, i)
                success = True
            except:
                success = False
            assert not success
        else:
            assert c.extrakt32(S, i) == expected_result
            assert c.extrakt32_mem(S, i) == expected_result
            assert c.extrakt32_storage(i, S) == expected_result

    print("Passed bytes32 extraction test")


def test_test_concat_bytes32():
    test_concat_bytes32 = """
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 164:
    return concat(inp2, inp, inp2)

def fivetimes(inp: bytes32) -> bytes <= 160:
    return concat(inp, inp, inp, inp, inp)
    """

    c = get_contract(test_concat_bytes32)
    assert c.sandwich(b"cow", b"\x35" * 32) == b"\x35" * 32 + b"cow" + b"\x35" * 32, c.sandwich(b"cow", b"\x35" * 32)
    assert c.sandwich(b"", b"\x46" * 32) == b"\x46" * 64
    assert c.sandwich(b"\x57" * 95, b"\x57" * 32) == b"\x57" * 159
    assert c.sandwich(b"\x57" * 96, b"\x57" * 32) == b"\x57" * 160
    assert c.sandwich(b"\x57" * 97, b"\x57" * 32) == b"\x57" * 161
    assert c.fivetimes(b"mongoose" * 4) == b"mongoose" * 20

    print("Passed concat bytes32 test")


def test_caller_code():
    caller_code = """
def foo() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=5)

def bar() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=3)

def baz() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=7)
    """

    c = get_contract(caller_code)
    assert c.foo() == b"moose"
    assert c.bar() == b"moo"
    assert c.baz() == b"moose\x00\x00"

    print('Passed raw call test')


def test_extract32_code():
    extract32_code = """
def foo(inp: bytes <= 32) -> num:
    return extract32(inp, 0, type=num128)

def bar(inp: bytes <= 32) -> num256:
    return extract32(inp, 0, type=num256)

def baz(inp: bytes <= 32) -> bytes32:
    return extract32(inp, 0, type=bytes32)

def fop(inp: bytes <= 32) -> bytes32:
    return extract32(inp, 0)

def foq(inp: bytes <= 32) -> address:
    return extract32(inp, 0, type=address)
    """

    c = get_contract(extract32_code)
    assert c.foo(b"\x00" * 30 + b"\x01\x01") == 257
    assert c.bar(b"\x00" * 30 + b"\x01\x01") == 257
    try:
        c.foo(b"\x80" + b"\x00" * 30)
        success = True
    except:
        success = False
    assert not success
    assert c.bar(b"\x80" + b"\x00" * 31) == 2**255

    assert c.baz(b"crow" * 8) == b"crow" * 8
    assert c.fop(b"crow" * 8) == b"crow" * 8
    assert c.foq(b"\x00" * 12 + b"3" * 20) == "0x" + "3" * 40
    try:
        c.foq(b"crow" * 8)
        success = True
    except:
        success = False
    assert not success

    print('Passed extract32 test')


def test_rlp_decoder_code():
    import rlp
    rlp_decoder_code = """
u: bytes <= 100

def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[0]

def fop() -> bytes32:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]

def foq() -> bytes <= 100:
    x = RLPList('\xc5\x83cow\x03', [bytes, num])
    return x[0]

def fos() -> num:
    x = RLPList('\xc5\x83cow\x03', [bytes, num])
    return x[1]

def fot() -> num256:
    x = RLPList('\xc5\x83cow\x03', [bytes, num256])
    return x[1]

def qoo(inp: bytes <= 100) -> address:
    x = RLPList(inp, [address, bytes32])
    return x[0]

def qos(inp: bytes <= 100) -> num:
    x = RLPList(inp, [num, num])
    return x[0] + x[1]

def qot(inp: bytes <= 100):
    x = RLPList(inp, [num, num])

def qov(inp: bytes <= 100):
    x = RLPList(inp, [num256, num256])

def roo(inp: bytes <= 100) -> address:
    self.u = inp
    x = RLPList(self.u, [address, bytes32])
    return x[0]

def too(inp: bytes <= 100) -> bool:
    x = RLPList(inp, [bool])
    return x[0]

def voo(inp: bytes <= 1024) -> num:
    x = RLPList(inp, [num, num, bytes32, num, bytes32, bytes])
    return x[1]
    """
    c = get_contract(rlp_decoder_code)

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
    try:
        c.qot(rlp.encode([7, 2**160]))
        success = True
    except:
        success = False
    assert not success
    c.qov(rlp.encode([7, 2**160]))
    try:
        c.qov(rlp.encode([2**160]))
        success = True
    except:
        success = False
    assert not success
    try:
        c.qov(rlp.encode([b'\x03', b'\x00\x01']))
        success = True
    except:
        success = False
    assert not success
    c.qov(rlp.encode([b'\x03', b'\x01']))
    c.qov(rlp.encode([b'\x03', b'']))
    try:
        c.qov(rlp.encode([b'\x03', b'\x00']))
        success = True
    except:
        success = False
    assert not success
    assert c.too(rlp.encode([b'\x01'])) is True
    assert c.too(rlp.encode([b''])) is False
    try:
        c.too(rlp.encode([b'\x02']))
        success = True
    except:
        success = False
    assert not success
    try:
        c.too(rlp.encode([b'\x00']))
        success = True
    except:
        success = False
    assert not success

    print('Passed RLP decoder tests')


def test_konkat_code():
    konkat_code = """
ecks: bytes32

def foo(x: bytes32, y: bytes32) -> bytes <= 64:
    selfecks = x
    return concat(selfecks, y)

def goo(x: bytes32, y: bytes32) -> bytes <= 64:
    self.ecks = x
    return concat(self.ecks, y)

def hoo(x: bytes32, y: bytes32) -> bytes <= 64:
    return concat(x, y)
    """

    c = get_contract(konkat_code)
    assert c.foo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32
    assert c.goo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32
    assert c.hoo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32

    print('Passed second concat tests')


def test_large_input_code():
    large_input_code = """
def foo(x: num) -> num:
    return 3
    """

    c = get_contract_with_gas_estimation(large_input_code)
    c.foo(1274124)
    c.foo(2**120)
    try:
        c.foo(2**130)
        success = True
    except:
        success = False
    assert not success


def test_large_input_code_2():
    large_input_code_2 = """
def __init__(x: num):
    y = x

def foo() -> num:
    return 5
    """

    c = get_contract(large_input_code_2, args=[17], sender=t.k0, value=0)
    try:
        c = get_contract(large_input_code_2, args=[2**130], sender=t.k0, value=0)
        success = True
    except:
        success = False
    assert not success

    print('Passed invalid input tests')





def test_test_bitwise():
    test_bitwise = """
def _bitwise_and(x: num256, y: num256) -> num256:
    return bitwise_and(x, y)

def _bitwise_or(x: num256, y: num256) -> num256:
    return bitwise_or(x, y)

def _bitwise_xor(x: num256, y: num256) -> num256:
    return bitwise_xor(x, y)

def _bitwise_not(x: num256) -> num256:
    return bitwise_not(x)

def _shift(x: num256, y: num) -> num256:
    return shift(x, y)
    """

    c = get_contract(test_bitwise)
    x = 126416208461208640982146408124
    y = 7128468721412412459
    assert c._bitwise_and(x, y) == (x & y)
    assert c._bitwise_or(x, y) == (x | y)
    assert c._bitwise_xor(x, y) == (x ^ y)
    assert c._bitwise_not(x) == 2**256 - 1 - x
    assert c._shift(x, 3) == x * 8
    assert c._shift(x, 255) == 0
    assert c._shift(y, 255) == 2**255
    assert c._shift(x, 256) == 0
    assert c._shift(x, 0) == x
    assert c._shift(x, -1) == x // 2
    assert c._shift(x, -3) == x // 8
    assert c._shift(x, -256) == 0

    print("Passed bitwise operation tests")


def test_selfcall_code_3():
    selfcall_code_3 = """
def _hashy2(x: bytes <= 100) -> bytes32:
    return sha3(x)

def return_hash_of_cow_x_30() -> bytes32:
    return self._hashy2("cowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcowcow")

def _len(x: bytes <= 100) -> num:
    return len(x)

def returnten() -> num:
    return self._len("badminton!")
    """

    c = get_contract(selfcall_code_3)
    assert c.return_hash_of_cow_x_30() == u.sha3(b'cow' * 30)
    assert c.returnten() == 10

    print("Passed single variable-size argument self-call test")


def test_multiple_levels():
    inner_code = """
def returnten() -> num:
    return 10
    """

    c = get_contract(inner_code)

    outer_code = """
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
    """

    c2 = get_contract(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    expected_forwarder_code_mask = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'[12:]
    c3 = c2.create_and_return_forwarder(c.address)
    assert s.head_state.get_code(c3)[:15] == expected_forwarder_code_mask[:15]
    assert s.head_state.get_code(c3)[35:] == expected_forwarder_code_mask[35:]

    print('Passed forwarder test')
    # TODO: This one is special
    print('Gas consumed: %d' % (s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used))


def test_multiple_levels2():
    inner_code = """
def returnten() -> num:
    assert False
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    try:
        c2.create_and_call_returnten(c.address)
        success = True
    except:
        success = False
    assert not success

    print('Passed forwarder exception test')


def test_minmax():
    minmax_test = """
def foo() -> decimal:
    return min(3, 5) + max(10, 20) + min(200.1, 400) + max(3000, 8000.02) + min(50000.003, 70000.004)

def goo() -> num256:
    return num256_add(min(as_num256(3), as_num256(5)), max(as_num256(40), as_num256(80)))
    """

    c = get_contract(minmax_test)
    assert c.foo() == 58223.123
    assert c.goo() == 83

    print("Passed min/max test")

def test_ecadd():
    ecadder = """
x3: num256[2]
y3: num256[2]
    
def _ecadd(x: num256[2], y: num256[2]) -> num256[2]:
    return ecadd(x, y)

def _ecadd2(x: num256[2], y: num256[2]) -> num256[2]:
    x2 = x
    y2 = [y[0], y[1]]
    return ecadd(x2, y2)

def _ecadd3(x: num256[2], y: num256[2]) -> num256[2]:
    self.x3 = x
    self.y3 = [y[0], y[1]]
    return ecadd(self.x3, self.y3)

    """
    c = get_contract(ecadder)

    # UNCOMMENT WHEN NEXT VERSION OF ETHEREUM IS RELEASED (these tests should pass then)
    # assert c._ecadd(G1, G1) == G1_times_two
    # assert c._ecadd2(G1, G1_times_two) == G1_times_three
    # assert c._ecadd3(G1, [0, 0]) == G1
    # assert c._ecadd3(G1, negative_G1) == [0, 0]

def test_ecmul():
    ecmuller = """
x3: num256[2]
y3: num256
    
def _ecmul(x: num256[2], y: num256) -> num256[2]:
    return ecmul(x, y)

def _ecmul2(x: num256[2], y: num256) -> num256[2]:
    x2 = x
    y2 = y
    return ecmul(x2, y2)

def _ecmul3(x: num256[2], y: num256) -> num256[2]:
    self.x3 = x
    self.y3 = y
    return ecmul(self.x3, self.y3)

"""
    c = get_contract(ecmuller)

    # UNCOMMENT WHEN NEXT VERSION OF ETHEREUM IS RELEASED (these tests should pass then)
    # assert c._ecmul(G1, 0) == [0 ,0]
    # assert c._ecmul(G1, 1) == G1
    # assert c._ecmul(G1, 3) == G1_times_three
    # assert c._ecmul(G1, curve_order - 1) == negative_G1
    # assert c._ecmul(G1, curve_order) == [0, 0]

def test_modmul():
    modexper = """
def exp(base: num256, exponent: num256, modulus: num256) -> num256:
      o = as_num256(1)
      for i in range(256):
          o = num256_mulmod(o, o, modulus)
          if bitwise_and(exponent, shift(as_num256(1), 255 - i)) != as_num256(0):
              o = num256_mulmod(o, base, modulus)
      return o
    """

    c = get_contract(modexper)
    assert c.exp(3, 5, 100) == 43
    assert c.exp(2, 997, 997) == 2
