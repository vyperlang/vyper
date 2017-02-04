from viper import parser, compile_lll
from viper import compiler_plugin
from ethereum import tester as t
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

s = t.state()
t.languages['viper'] = compiler_plugin.Compiler() 

null_code = """
def foo():
    pass
"""

c = s.abi_contract(null_code, language='viper')
c.foo()

print('Successfully executed a null function')
print('Gas estimate', t.languages['viper'].gas_estimate(null_code)['foo'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

basic_code = """

def foo(x: num) -> num:
    return x * 2

"""

c = s.abi_contract(basic_code, language='viper')
assert c.foo(9) == 18
print('Passed basic code test')
print('Gas estimate', t.languages['viper'].gas_estimate(basic_code)['foo'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

basic_repeater = """

def repeat(z: num) -> num:
    x = 0
    for i in range(6):
        x = x + z
    return(x)
"""

c = s.abi_contract(basic_repeater, language='viper')
assert c.repeat(9) == 54
print('Passed basic repeater test')
print('Gas estimate', t.languages['viper'].gas_estimate(basic_repeater)['repeat'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

more_complex_repeater = """
def repeat() -> num:
    out = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
"""


c = s.abi_contract(more_complex_repeater, language='viper')
assert c.repeat() == 666666
print('Passed complex repeater test')
print('Gas estimate', t.languages['viper'].gas_estimate(more_complex_repeater)['repeat'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

offset_repeater = """
def sum() -> num:
    out = 0
    for i in range(80, 121):
        out = out + i
    return(out)
"""

c = s.abi_contract(offset_repeater, language='viper')
assert c.sum() == 4100

print('Passed repeater with offset test')

offset_repeater_2 = """
def sum(frm: num, to: num) -> num:
    out = 0
    for i in range(frm, frm + 101):
        if i == to:
            break
        out = out + i
    return(out)
"""

c = s.abi_contract(offset_repeater_2, language='viper')
assert c.sum(100, 99999) == 15150
assert c.sum(70, 131) == 6100

print('Passed more complex repeater with offset test')

array_accessor = """
def test_array(x: num, y: num, z: num, w: num) -> num:
    a: num[4]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[0] * 1000 + a[1] * 100 + a[2] * 10 + a[3]
"""

c = s.abi_contract(array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed basic array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(array_accessor)['test_array'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

two_d_array_accessor = """
def test_array(x: num, y: num, z: num, w: num) -> num:
    a: num[2][2]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
"""

c = s.abi_contract(two_d_array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed complex array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(two_d_array_accessor)['test_array'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)


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

c = s.abi_contract(digit_reverser, language='viper')
assert c.reverse_digits(123456) == 654321
print('Passed digit reverser test')
print('Gas estimate', t.languages['viper'].gas_estimate(digit_reverser)['reverse_digits'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

arbitration_code = """
buyer: address
seller: address
arbitrator: address

def setup(_seller: address, _arbitrator: address):
    if not self.buyer:
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)

"""

c = s.abi_contract(arbitration_code, language='viper', endowment=1)
c.setup(t.a1, t.a2, sender=t.k0)
try:
    c.finalize(sender=t.k1)
    success = True
except t.TransactionFailed:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

arbitration_code_with_init = """
buyer: address
seller: address
arbitrator: address

def __init__(_seller: address, _arbitrator: address):
    if not self.buyer:
        self.buyer = msg.sender
        self.seller = _seller
        self.arbitrator = _arbitrator

def finalize():
    assert msg.sender == self.buyer or msg.sender == self.arbitrator
    send(self.seller, self.balance)

def refund():
    assert msg.sender == self.seller or msg.sender == self.arbitrator
    send(self.buyer, self.balance)
"""

c = s.abi_contract(arbitration_code_with_init, language='viper', constructor_parameters=[t.a1, t.a2], sender=t.k0, endowment=1)
try:
    c.finalize(sender=t.k1)
    success = True
except t.TransactionFailed:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test with initializer')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

decimal_test = """
def foo() -> num:
    return(floor(999.0))

def fop() -> num:
    return(floor(333.0 + 666.0))

def foq() -> num:
    return(floor(1332.1 - 333.1))

def bar() -> num:
    return(floor(27.0 * 37.0))

def baz() -> num:
    x = 27.0
    return(floor(x * 37.0))

def baffle() -> num:
    return(floor(27.0 * 37))

def mok() -> num:
    return(floor(999999.0 / 7.0 / 11.0 / 13.0))

def mol() -> num:
    return(floor(499.5 / 0.5))

def mom() -> num:
    return(floor(1498.5 / 1.5))

def mon() -> num:
    return(floor(2997.0 / 3))

def moo() -> num:
    return(floor(2997 / 3.0))

def foom() -> num:
    return(floor(1999.0 % 1000.0))

def foon() -> num:
    return(floor(1999.0 % 1000))

def foop() -> num:
    return(floor(1999 % 1000.0))
"""

c = s.abi_contract(decimal_test, language='viper')
pre_gas = s.state.receipts[-1].gas_used
pre_txs = len(s.state.receipts)
assert c.foo() == 999
assert c.fop() == 999
assert c.foq() == 999
assert c.bar() == 999
assert c.baz() == 999
assert c.baffle() == 999
assert c.mok() == 999
assert c.mol() == 999
assert c.mom() == 999
assert c.mon() == 999
assert c.moo() == 999
assert c.foom() == 999
assert c.foon() == 999
assert c.foop() == 999
post_gas = s.state.receipts[-1].gas_used
post_txs = len(s.state.receipts)

estimate = t.languages['viper'].gas_estimate(decimal_test)


print('Passed basic addition, subtraction and multiplication tests')
print('Gas estimate', sum(estimate.values()), 'actual', post_gas - pre_gas - s.last_tx.intrinsic_gas_used * (post_txs - pre_txs))

harder_decimal_test = """
def phooey() -> num:
    x = 10000.0
    for i in range(4):
        x = x * 1.2
    return(floor(x))
"""


c = s.abi_contract(harder_decimal_test, language='viper')
assert c.phooey() == 20736

print('Passed fractional multiplication test')

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

c = s.abi_contract(break_test, language='viper')
assert c.log(1) == 0
assert c.log(2) == 3
assert c.log(10) == 10
assert c.log(200) == 23
print('Passed for-loop break test')

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


c = s.abi_contract(break_test_2, language='viper')
assert c.log(1) == 0
assert c.log(2) == 3
assert c.log(10) == 10
assert c.log(200) == 23
assert c.log(4000000) == 66
print('Passed for-loop break test 2')

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

c = s.abi_contract(augassign_test, language='viper')

assert c.augadd(5, 12) == 17
assert c.augmul(5, 12) == 60
assert c.augsub(5, 12) == -7
assert c.augdiv(5, 12) == 0
assert c.augmod(5, 12) == 5
print('Passed aug-assignment test')

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
c = s.abi_contract(break_test_3, language='viper')
assert c.log(1) == 0
assert c.log(2) == 3
assert c.log(10) == 10
assert c.log(200) == 23
assert c.log(4000000) == 66
print('Passed aug-assignment break composite test')


init_argument_test = """
moose: num
def __init__(_moose: num):
    self.moose = _moose

def returnMoose() -> num:
    return self.moose
"""

c = s.abi_contract(init_argument_test, language='viper', constructor_parameters=[5])
assert c.returnMoose() == 5
print('Passed init argument test')
print('Gas estimate', t.languages['viper'].gas_estimate(init_argument_test)['returnMoose'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

permanent_variables_test = """
var: {a: num, b: num}
def __init__(a: num, b: num):
    self.var.a = a
    self.var.b = b

def returnMoose() -> num:
    return self.var.a * 10 + self.var.b
"""

c = s.abi_contract(permanent_variables_test, language='viper', constructor_parameters=[5, 7])
assert c.returnMoose() == 57
print('Passed init argument and variable member test')
print('Gas estimate', t.languages['viper'].gas_estimate(permanent_variables_test)['returnMoose'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)


crowdfund = """

funders: {sender: address, value: wei_value}[num]
nextFunderIndex: num
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: num
timelimit: timedelta

def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

def participate():
    assert block.timestamp < self.deadline
    nfi = self.nextFunderIndex
    self.funders[nfi].sender = msg.sender
    self.funders[nfi].value = msg.value
    self.nextFunderIndex = nfi + 1

def expired() -> bool(const):
    return block.timestamp >= self.deadline

def timestamp() -> timestamp(const):
    return block.timestamp

def deadline() -> timestamp(const):
    return self.deadline

def timelimit() -> timedelta(const):
    return self.timelimit

def reached() -> bool(const):
    return self.balance >= self.goal

def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

def refund():
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i].sender = "0x0000000000000000000000000000000000000000"
        self.funders[i].value = 0
    self.refundIndex = ind + 30

"""

c = s.abi_contract(crowdfund, language='viper', constructor_parameters=[t.a1, 50, 600])


c.participate(value = 5)
assert c.timelimit() == 600
assert c.deadline() - c.timestamp() == 600
assert not c.expired()
assert not c.reached()
c.participate(value = 49)
assert c.reached()
pre_bal = s.state.get_balance(t.a1)
s.state.timestamp += 1000
assert c.expired()
c.finalize()
post_bal = s.state.get_balance(t.a1)
assert post_bal - pre_bal == 54

c = s.abi_contract(crowdfund, language='viper', constructor_parameters=[t.a1, 50, 600])
c.participate(value = 1, sender=t.k3)
c.participate(value = 2, sender=t.k4)
c.participate(value = 3, sender=t.k5)
c.participate(value = 4, sender=t.k6)
s.state.timestamp += 1000
assert c.expired()
assert not c.reached()
pre_bals = [s.state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
c.refund()
post_bals = [s.state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
assert [y-x for x, y in zip(pre_bals, post_bals)] == [1,2,3,4]

print('Passed composite crowdfund test')

comment_test = """

def foo() -> num:
    # Returns 3
    return 3
"""

c = s.abi_contract(comment_test, language='viper')
assert c.foo() == 3
print('Passed comment test')

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

c = s.abi_contract(packing_test, language='viper')
assert c.foo() == 1023, c.foo()
assert c.fop() == 1023, c.fop()
print('Passed packing test')

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

c = s.abi_contract(multi_setter_test, language='viper')
assert c.foo() == 321
assert c.fop() == 654321
assert c.goo() == 321
assert c.gop() == 654321
assert c.hoo() == 0
assert c.hop() == 321
assert c.joo() == 0
assert c.jop() == 321
print('Passed multi-setter literal test')

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

c = s.abi_contract(multi_setter_struct_test, language='viper')
assert c.foo() == 654321
assert c.fop() == 87198763254321
assert c.goo() == 654321
assert c.gop() == 87198763254321

print('Passed multi-setter struct test')

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

c = s.abi_contract(type_converter_setter_test, language='viper')
assert c.foo() == 4321
assert c.foo() == 4321
print('Passed type-conversion struct test')

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

c = s.abi_contract(composite_setter_test, language='viper')
assert c.foo() == 4625
assert c.fop() == 4625
assert c.foq() == 4020
print('Passed composite struct test')

crowdfund2 = """

funders: {sender: address, value: wei_value}[num]
nextFunderIndex: num
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: num
timelimit: timedelta

def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

def participate():
    assert block.timestamp < self.deadline
    nfi = self.nextFunderIndex
    self.funders[nfi] = {sender: msg.sender, value: msg.value}
    self.nextFunderIndex = nfi + 1

def expired() -> bool(const):
    return block.timestamp >= self.deadline

def timestamp() -> timestamp(const):
    return block.timestamp

def deadline() -> timestamp(const):
    return self.deadline

def timelimit() -> timedelta(const):
    return self.timelimit

def reached() -> bool(const):
    return self.balance >= self.goal

def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

def refund():
    ind = self.refundIndex
    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None
    self.refundIndex = ind + 30

"""

c = s.abi_contract(crowdfund2, language='viper', constructor_parameters=[t.a1, 50, 600])


c.participate(value = 5)
assert c.timelimit() == 600
assert c.deadline() - c.timestamp() == 600
assert not c.expired()
assert not c.reached()
c.participate(value = 49)
assert c.reached()
pre_bal = s.state.get_balance(t.a1)
s.state.timestamp += 1000
assert c.expired()
c.finalize()
post_bal = s.state.get_balance(t.a1)
assert post_bal - pre_bal == 54

c = s.abi_contract(crowdfund2, language='viper', constructor_parameters=[t.a1, 50, 600])
c.participate(value = 1, sender=t.k3)
c.participate(value = 2, sender=t.k4)
c.participate(value = 3, sender=t.k5)
c.participate(value = 4, sender=t.k6)
s.state.timestamp += 1000
assert c.expired()
assert not c.reached()
pre_bals = [s.state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
c.refund()
post_bals = [s.state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
assert [y-x for x, y in zip(pre_bals, post_bals)] == [1,2,3,4]

print('Passed second composite crowdfund test')

test_bytes = """
def foo(x: bytes <= 100) -> bytes <= 100:
    return x
"""

c = s.abi_contract(test_bytes, language='viper')
moo_result = c.foo(b'cow')
assert moo_result == b'cow'

print('Passed basic bytes test')

assert c.foo(b'\x35' * 100) == b'\x35' * 100

print('Passed max-length bytes test')

try:
    c.foo(b'\x35' * 101)
    assert False
except:
    pass

print('Failed input-too-long test as expected')

test_bytes2 = """
def foo(x: bytes <= 100) -> bytes <= 100:
    y = x
    return y
"""

c = s.abi_contract(test_bytes2, language='viper')
assert c.foo(b'cow') == b'cow'
assert c.foo(b'') == b''
assert c.foo(b'\x35' * 63) == b'\x35' * 63
assert c.foo(b'\x35' * 64) == b'\x35' * 64
assert c.foo(b'\x35' * 65) == b'\x35' * 65

print('Passed string copying test')

test_bytes3 = """
x: num
maa: bytes <= 60
y: num

def __init__():
    self.x = 27
    self.y = 37

def set_maa(inp: bytes <= 60):
    self.maa = inp

def set_maa2(inp: bytes <= 60):
    ay = inp
    self.maa = ay

def get_maa() -> bytes <= 60:
    return self.maa

def get_maa2() -> bytes <= 60:
    ay = self.maa
    return ay

def get_xy() -> num:
    return self.x * self.y
"""

c = s.abi_contract(test_bytes3, language='viper')
c.set_maa(b"pig")
assert c.get_maa() == b"pig"
assert c.get_maa2() == b"pig"
c.set_maa2(b"")
assert c.get_maa() == b""
assert c.get_maa2() == b""
c.set_maa(b"\x44" * 60)
assert c.get_maa() == b"\x44" * 60
assert c.get_maa2() == b"\x44" * 60
c.set_maa2(b"mongoose")
assert c.get_maa() == b"mongoose"
assert c.get_xy() == 999

print('Passed advanced string copying test')

test_bytes4 = """
a: bytes <= 60
def foo(inp: bytes <= 60) -> bytes <= 60:
    self.a = inp
    self.a = None
    return self.a

def bar(inp: bytes <= 60) -> bytes <= 60:
    b = inp
    b = None
    return b
"""

c = s.abi_contract(test_bytes4, language='viper')
assert c.foo() == b"", c.foo()
assert c.bar() == b""

print('Passed string deleting test')

test_bytes5 = """
g: {a: bytes <= 50, b: bytes <= 50}

def foo(inp1: bytes <= 40, inp2: bytes <= 45):
    self.g = {a: inp1, b: inp2}

def check1() -> bytes <= 50:
    return self.g.a

def check2() -> bytes <= 50:
    return self.g.b

def bar(inp1: bytes <= 40, inp2: bytes <= 45) -> bytes <= 50:
    h = {a: inp1, b: inp2}
    return h.a

def bat(inp1: bytes <= 40, inp2: bytes <= 45) -> bytes <= 50:
    h = {a: inp1, b: inp2}
    return h.b

def quz(inp1: bytes <= 40, inp2: bytes <= 45):
    h = {a: inp1, b: inp2}
    self.g = h
"""

c = s.abi_contract(test_bytes5, language='viper')
c.foo(b"cow", b"horse")
assert c.check1() == b"cow"
assert c.check2() == b"horse"
assert c.bar(b"pig", b"moose") == b"pig"
assert c.bat(b"pig", b"moose") == b"moose"
c.quz(b"badminton", b"fluffysheep")
assert c.check1() == b"badminton"
assert c.check2() == b"fluffysheep"

print('Passed string struct test')
