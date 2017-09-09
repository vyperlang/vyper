import pytest
from .setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_basic_repeater():
    basic_repeater = """

def repeat(z: num) -> num:
    x = 0
    for i in range(6):
        x = x + z
    return(x)
    """
    c = get_contract_with_gas_estimation(basic_repeater)
    assert c.repeat(9) == 54
    print('Passed basic repeater test')


def test_more_complex_repeater():
    more_complex_repeater = """
def repeat() -> num:
    out = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
    """
    c = get_contract_with_gas_estimation(more_complex_repeater)
    assert c.repeat() == 666666
    print('Passed complex repeater test')


def test_offset_repeater():
    offset_repeater = """
def sum() -> num:
    out = 0
    for i in range(80, 121):
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater)
    assert c.sum() == 4100

    print('Passed repeater with offset test')

def test_offset_repeater_2():
    offset_repeater_2 = """
def sum(frm: num, to: num) -> num:
    out = 0
    for i in range(frm, frm + 101):
        if i == to:
            break
        out = out + i
    return(out)
    """

    c = get_contract_with_gas_estimation(offset_repeater_2)
    assert c.sum(100, 99999) == 15150
    assert c.sum(70, 131) == 6100

    print('Passed more complex repeater with offset test')


def test_digit_reverser():
    digit_reverser = """

def reverse_digits(x: num) -> num:
    dig: num[6]
    z = x
    for i in range(6):
        dig[i] = z % 10
        z = z / 10
    o = 0
    for i in range(6):
        o = o * 10 + dig[i]
    return o

    """

    c = get_contract_with_gas_estimation(digit_reverser)
    assert c.reverse_digits(123456) == 654321
    print('Passed digit reverser test')


def test_state_accessor():
    state_accessor = """
y: num[num]

def oo():
    self.y[3] = 5

def foo() -> num:
    return self.y[3]

    """

    c = get_contract_with_gas_estimation(state_accessor)
    c.oo()
    assert c.foo() == 5
    print('Passed basic state accessor test')


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


def test_break_test():
    break_test = """
def log(n: num) -> num:
    c = n * 1.0
    output = 0
    for i in range(400):
        c = c / 1.2589
        if c < 1.0:
            output = i
            break
    return output
    """

    c = get_contract_with_gas_estimation(break_test)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    print('Passed for-loop break test')

def test_break_test_2():
    break_test_2 = """
def log(n: num) -> num:
    c = n * 1.0
    output = 0
    for i in range(40):
        if c < 10:
            output = i * 10
            break
        c = c / 10
    for i in range(10):
        c = c / 1.2589
        if c < 1.0:
            output = output + i
            break
    return output
    """


    c = get_contract_with_gas_estimation(break_test_2)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    assert c.log(4000000) == 66
    print('Passed for-loop break test 2')

def test_augassign_test():
    augassign_test = """
def augadd(x: num, y: num) -> num:
    z = x
    z += y
    return z

def augmul(x: num, y: num) -> num:
    z = x
    z *= y
    return z

def augsub(x: num, y: num) -> num:
    z = x
    z -= y
    return z

def augdiv(x: num, y: num) -> num:
    z = x
    z /= y
    return z

def augmod(x: num, y: num) -> num:
    z = x
    z %= y
    return z
    """

    c = get_contract(augassign_test)

    assert c.augadd(5, 12) == 17
    assert c.augmul(5, 12) == 60
    assert c.augsub(5, 12) == -7
    assert c.augdiv(5, 12) == 0
    assert c.augmod(5, 12) == 5
    print('Passed aug-assignment test')

def test_break_test_3():
    break_test_3 = """
def log(n: num) -> num:
    c = decimal(n)
    output = 0
    for i in range(40):
        if c < 10:
            output = i * 10
            break
        c /= 10
    for i in range(10):
        c /= 1.2589
        if c < 1:
            output = output + i
            break
    return output
    """
    c = get_contract_with_gas_estimation(break_test_3)
    assert c.log(1) == 0
    assert c.log(2) == 3
    assert c.log(10) == 10
    assert c.log(200) == 23
    assert c.log(4000000) == 66
    print('Passed aug-assignment break composite test')

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


def test_comment_test():
    comment_test = """

def foo() -> num:
    # Returns 3
    return 3
    """

    c = get_contract_with_gas_estimation(comment_test)
    assert c.foo() == 3
    print('Passed comment test')


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


def test_multi_setter_test():
    multi_setter_test = """
foo: num[3]
bar: num[3][3]
def foo() -> num:
    self.foo = [1, 2, 3]
    return(self.foo[0] + self.foo[1] * 10 + self.foo[2] * 100)

def fop() -> num:
    self.bar[0] = [1, 2, 3]
    self.bar[1] = [4, 5, 6]
    return self.bar[0][0] + self.bar[0][1] * 10 + self.bar[0][2] * 100 + \
        self.bar[1][0] * 1000 + self.bar[1][1] * 10000 + self.bar[1][2] * 100000

def goo() -> num:
    goo: num[3]
    goo = [1, 2, 3]
    return(goo[0] + goo[1] * 10 + goo[2] * 100)

def gop() -> num: # Following a standard naming scheme; nothing to do with the US republican party
    gar: num[3][3]
    gar[0] = [1, 2, 3]
    gar[1] = [4, 5, 6]
    return gar[0][0] + gar[0][1] * 10 + gar[0][2] * 100 + \
        gar[1][0] * 1000 + gar[1][1] * 10000 + gar[1][2] * 100000

def hoo() -> num:
    self.foo = None
    return(self.foo[0] + self.foo[1] * 10 + self.foo[2] * 100)

def hop() -> num:
    self.bar[1] = None
    return self.bar[0][0] + self.bar[0][1] * 10 + self.bar[0][2] * 100 + \
        self.bar[1][0] * 1000 + self.bar[1][1] * 10000 + self.bar[1][2] * 100000

def joo() -> num:
    goo: num[3]
    goo = [1, 2, 3]
    goo = None
    return(goo[0] + goo[1] * 10 + goo[2] * 100)

def jop() -> num:
    gar: num[3][3]
    gar[0] = [1, 2, 3]
    gar[1] = [4, 5, 6]
    gar[1] = None
    return gar[0][0] + gar[0][1] * 10 + gar[0][2] * 100 + \
        gar[1][0] * 1000 + gar[1][1] * 10000 + gar[1][2] * 100000

    """

    c = get_contract(multi_setter_test)
    assert c.foo() == 321
    assert c.fop() == 654321
    assert c.goo() == 321
    assert c.gop() == 654321
    assert c.hoo() == 0
    assert c.hop() == 321
    assert c.joo() == 0
    assert c.jop() == 321
    print('Passed multi-setter literal test')


def test_multi_setter_struct_test():
    multi_setter_struct_test = """
foo: {foo: num, bar: num}[3]
z: {foo: num[3], bar: {a: num, b: num}[2]}[2]

def foo() -> num:
    self.foo[0] = {foo: 1, bar: 2}
    self.foo[1] = {foo: 3, bar: 4}
    self.foo[2] = {foo: 5, bar: 6}
    return self.foo[0].foo + self.foo[0].bar * 10 + self.foo[1].foo * 100 + \
        self.foo[1].bar * 1000 + self.foo[2].foo * 10000 + self.foo[2].bar * 100000

def fop() -> num:
    self.z = [{foo: [1, 2, 3], bar: [{a: 4, b: 5}, {a: 2, b: 3}]},
              {foo: [6, 7, 8], bar: [{a: 9, b: 1}, {a: 7, b: 8}]}]
    return self.z[0].foo[0] + self.z[0].foo[1] * 10 + self.z[0].foo[2] * 100 + \
        self.z[0].bar[0].a * 1000 + self.z[0].bar[0].b * 10000 + self.z[0].bar[1].a * 100000 + self.z[0].bar[1].b * 1000000 + \
        self.z[1].foo[0] * 10000000 + self.z[1].foo[1] * 100000000 + self.z[1].foo[2] * 1000000000 + \
        self.z[1].bar[0].a * 10000000000 + self.z[1].bar[0].b * 100000000000 + \
        self.z[1].bar[1].a * 1000000000000 + self.z[1].bar[1].b * 10000000000000

def goo() -> num:
    goo: {foo: num, bar: num}[3]
    goo[0] = {foo: 1, bar: 2}
    goo[1] = {foo: 3, bar: 4}
    goo[2] = {foo: 5, bar: 6}
    return goo[0].foo + goo[0].bar * 10 + goo[1].foo * 100 + \
        goo[1].bar * 1000 + goo[2].foo * 10000 + goo[2].bar * 100000

def gop() -> num:
    zed = [{foo: [1, 2, 3], bar: [{a: 4, b: 5}, {a: 2, b: 3}]},
           {foo: [6, 7, 8], bar: [{a: 9, b: 1}, {a: 7, b: 8}]}]
    return zed[0].foo[0] + zed[0].foo[1] * 10 + zed[0].foo[2] * 100 + \
        zed[0].bar[0].a * 1000 + zed[0].bar[0].b * 10000 + zed[0].bar[1].a * 100000 + zed[0].bar[1].b * 1000000 + \
        zed[1].foo[0] * 10000000 + zed[1].foo[1] * 100000000 + zed[1].foo[2] * 1000000000 + \
        zed[1].bar[0].a * 10000000000 + zed[1].bar[0].b * 100000000000 + \
        zed[1].bar[1].a * 1000000000000 + zed[1].bar[1].b * 10000000000000
    """

    c = get_contract(multi_setter_struct_test)
    assert c.foo() == 654321
    assert c.fop() == 87198763254321
    assert c.goo() == 654321
    assert c.gop() == 87198763254321

    print('Passed multi-setter struct test')


def test_type_converter_setter_test():
    type_converter_setter_test = """
mom: {a: {c: num}[3], b: num}
non: {a: {c: decimal}[3], b:num}
pop: decimal[2][2]

def foo() -> num:
    self.mom = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    self.non = self.mom
    return floor(self.non.a[0].c + self.non.a[1].c * 10 + self.non.a[2].c * 100 + self.non.b * 1000)

def goo() -> num:
    self.pop = [[1, 2], [3, 4.0]]
    return floor(self.pop[0][0] + self.pop[0][1] * 10 + self.pop[1][0] * 100 + self.pop[1][1] * 1000)
    """

    c = get_contract(type_converter_setter_test)
    assert c.foo() == 4321
    assert c.foo() == 4321
    print('Passed type-conversion struct test')


def test_composite_setter_test():
    composite_setter_test = """
mom: {a: {c: num}[3], b:num}
qoq: {c: num}
def foo() -> num:
    self.mom = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    non = {c: 5}
    self.mom.a[0] = non
    non = {c: 6}
    self.mom.a[2] = non
    return self.mom.a[0].c + self.mom.a[1].c * 10 + self.mom.a[2].c * 100 + self.mom.b * 1000

def fop() -> num:
    popp = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    self.qoq = {c: 5}
    popp.a[0] = self.qoq
    self.qoq = {c: 6}
    popp.a[2] = self.qoq
    return popp.a[0].c + popp.a[1].c * 10 + popp.a[2].c * 100 + popp.b * 1000

def foq() -> num:
    popp = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    popp.a[0] = None
    popp.a[2] = None
    return popp.a[0].c + popp.a[1].c * 10 + popp.a[2].c * 100 + popp.b * 1000
    """

    c = get_contract(composite_setter_test)
    assert c.foo() == 4625
    assert c.fop() == 4625
    assert c.foq() == 4020
    print('Passed composite struct test')


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


def test_getter_code():
    getter_code = """
x: public(wei_value)
y: public(num[5])
z: public(bytes <= 100)
w: public({
    a: wei_value,
    b: num[7],
    c: bytes <= 100,
    d: num[address],
    e: num[3][3],
    f: timestamp,
    g: wei_value
}[num])

def __init__():
    self.x = as_wei_value(7, wei)
    self.y[1] = 9
    self.z = "cow"
    self.w[1].a = 11
    self.w[1].b[2] = 13
    self.w[1].c = "horse"
    self.w[1].d[0x1234567890123456789012345678901234567890] = 15
    self.w[2].e[1][2] = 17
    self.w[3].f = 750
    self.w[3].g = 751
    """

    c = get_contract(getter_code)
    assert c.get_x() == 7
    assert c.get_y(1) == 9
    assert c.get_z() == b"cow"
    assert c.get_w__a(1) == 11
    assert c.get_w__b(1, 2) == 13
    assert c.get_w__c(1) == b"horse"
    assert c.get_w__d(1, "0x1234567890123456789012345678901234567890") == 15
    assert c.get_w__e(2, 1, 2) == 17
    assert c.get_w__f(3) == 750
    assert c.get_w__g(3) == 751

    print('Passed getter tests')


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


def test_conditional_return_code():
    conditional_return_code = """
def foo(i: bool) -> num:
    if i:
        return 5
    else:
        assert 2
        return 7
    return 11
    """

    c = get_contract_with_gas_estimation(conditional_return_code)
    assert c.foo(True) == 5
    assert c.foo(False) == 7

    print('Passed conditional return tests')


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


def test_loggy_code():
    loggy_code = """
s: bytes <= 100

def foo():
    raw_log([], "moo")

def goo():
    raw_log([0x1234567812345678123456781234567812345678123456781234567812345678], "moo2")

def hoo():
    self.s = "moo3"
    raw_log([], self.s)

def ioo(inp: bytes <= 100):
    raw_log([], inp)
    """

    c = get_contract(loggy_code)
    c.foo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo'
    c.goo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo2'
    assert s.head_state.receipts[-1].logs[0].topics == [0x1234567812345678123456781234567812345678123456781234567812345678]
    c.hoo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo3'
    c.ioo(b"moo4")
    assert s.head_state.receipts[-1].logs[0].data == b'moo4'
    print("Passed raw log tests")


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


def test_selfcall_code():
    selfcall_code = """
def foo() -> num:
    return 3

def bar() -> num:
    return self.foo()
    """

    c = get_contract(selfcall_code)
    assert c.bar() == 3

    print("Passed no-argument self-call test")


def test_selfcall_code_2():
    selfcall_code_2 = """
def double(x: num) -> num:
    return x * 2

def returnten() -> num:
    return self.double(5)

def _hashy(x: bytes32) -> bytes32:
    return sha3(x)

def return_hash_of_rzpadded_cow() -> bytes32:
    return self._hashy(0x636f770000000000000000000000000000000000000000000000000000000000)
    """

    c = get_contract(selfcall_code_2)
    assert c.returnten() == 10
    assert c.return_hash_of_rzpadded_cow() == u.sha3(b'cow' + b'\x00' * 29)

    print("Passed single fixed-size argument self-call test")


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


def test_selfcall_code_4():
    selfcall_code_4 = """
def summy(x: num, y: num) -> num:
    return x + y

def catty(x: bytes <= 5, y: bytes <= 5) -> bytes <= 10:
    return concat(x, y)

def slicey1(x: bytes <= 10, y: num) -> bytes <= 10:
    return slice(x, start=0, len=y)

def slicey2(y: num, x: bytes <= 10) -> bytes <= 10:
    return slice(x, start=0, len=y)

def returnten() -> num:
    return self.summy(3, 7)

def return_mongoose() -> bytes <= 10:
    return self.catty("mon", "goose")

def return_goose() -> bytes <= 10:
    return self.slicey1("goosedog", 5)

def return_goose2() -> bytes <= 10:
    return self.slicey2(5, "goosedog")
    """

    c = get_contract(selfcall_code_4)
    assert c.returnten() == 10
    assert c.return_mongoose() == b"mongoose"
    assert c.return_goose() == b"goose"
    assert c.return_goose2() == b"goose"

    print("Passed multi-argument self-call test")

def test_selfcall_code_5():
    selfcall_code_5 = """
counter: num

def increment():
    self.counter += 1

def returnten() -> num:
    for i in range(10):
        self.increment()
    return self.counter
    """
    c = get_contract(selfcall_code_5)
    assert c.returnten() == 10

    print("Passed self-call statement test")


def test_selfcall_code_6():
    selfcall_code_6 = """
excls: bytes <= 32

def set_excls(arg: bytes <= 32):
    self.excls = arg

def underscore() -> bytes <= 1:
    return "_"

def hardtest(x: bytes <= 100, y: num, z: num, a: bytes <= 100, b: num, c: num) -> bytes <= 201:
    return concat(slice(x, start=y, len=z), self.underscore(), slice(a, start=b, len=c))

def return_mongoose_revolution_32_excls() -> bytes <= 201:
    self.set_excls("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
    return self.hardtest("megamongoose123", 4, 8, concat("russian revolution", self.excls), 8, 42)
    """

    c = get_contract(selfcall_code_6)
    assert c.return_mongoose_revolution_32_excls() == b"mongoose_revolution" + b"!" * 32

    print("Passed composite self-call test")


def test_clamper_test_code():
    clamper_test_code = """
def foo(s: bytes <= 3) -> bytes <= 3:
    return s
    """

    c = get_contract(clamper_test_code, value=1)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    try:
        c.foo(b"cate")
        success = True
    except t.TransactionFailed:
        success = False
    assert not success

    print("Passed bytearray clamping test")


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


def test_internal_test():
    internal_test = """
@internal
def a() -> num:
    return 5

def returnten() -> num:
    return self.a() * 2
    """

    c = get_contract(internal_test)
    assert c.returnten() == 10

    print("Passed internal function test")


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
