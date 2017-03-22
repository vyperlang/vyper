from viper import parser, compile_lll
from viper import compiler
from ethereum import tester as t
from ethereum import transactions, state_transition
from ethereum import utils as u
import rlp
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
#configure_logging(config_string=config_string)

s = t.state()
t.languages['viper'] = compiler.Compiler() 

# Install RLP decoder library
s.state.set_balance('0xfe2ec957647679d210034b65e9c7db2452910b0c', 9350880000000000)
state_transition.apply_transaction(s.state, rlp.decode(u.decode_hex('f903bd808506fc23ac008304c1908080b903aa6103988061000e6000396103a65660006101bf5361202059905901600090526101008152602081019050602052600060605261040036018060200159905901600090528181526020810190509050608052600060e0527f0100000000000000000000000000000000000000000000000000000000000000600035046101005260c061010051121561007e57fe5b60f86101005112156100a95760c061010051036001013614151561009e57fe5b6001610120526100ec565b60f761010051036020036101000a600161012051013504610140526101405160f7610100510360010101361415156100dd57fe5b60f76101005103600101610120525b5b366101205112156102ec577f01000000000000000000000000000000000000000000000000000000000000006101205135046101005260e0516060516020026020510152600160605101606052608061010051121561017a57600160e0516080510152600161012051602060e0516080510101376001610120510161012052602160e0510160e0526102da565b60b8610100511215610218576080610100510360e05160805101526080610100510360016101205101602060e05160805101013760816101005114156101ef5760807f010000000000000000000000000000000000000000000000000000000000000060016101205101350412156101ee57fe5b5b600160806101005103016101205101610120526020608061010051030160e0510160e0526102d9565b60c06101005112156102d65760b761010051036020036101000a6001610120510135046101405260007f0100000000000000000000000000000000000000000000000000000000000000600161012051013504141561027357fe5b603861014051121561028157fe5b6101405160e05160805101526101405160b761010051600161012051010103602060e05160805101013761014051600160b7610100510301016101205101610120526020610140510160e0510160e0526102d8565bfe5b5b5b602060605113156102e757fe5b6100ed565b60e051606051602002602051015261082059905901600090526108008152602081019050610160526000610120525b6060516101205113151561035c576020602060605102610120516020026020510151010161012051602002610160510152600161012051016101205261031b565b60e0518060206020606051026101605101018260805160006004600a8705601201f161038457fe5b50602060e051602060605102010161016051f35b6000f31b2d4f'), transactions.Transaction))
assert s.state.get_code('0x0b8178879f97f2ada01fb8d219ee3d0ad74e91e0')

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
        self.funders[i].sender = 0x0000000000000000000000000000000000000000
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

print('Passed input-too-long test')

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

c = s.abi_contract(test_slice, language='viper')
x = c.foo("badminton")
assert x == b"min", x

assert c.bar("badminton") == 35

print('Passed slice test')

test_slice2 = """
def slice_tower_test(inp1: bytes <= 50) -> bytes <= 50:
    inp = inp1
    for i in range(1, 11):
        inp = slice(inp, start=1, len=30 - i * 2)
    return inp
"""

c = s.abi_contract(test_slice2, language='viper')
x = c.slice_tower_test("abcdefghijklmnopqrstuvwxyz1234")
assert x == b"klmnopqrst"

print('Passed advanced slice test')

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

c = s.abi_contract(test_slice3, language='viper')
x = c.foo("badminton")
assert x == b"min", x

assert c.bar("badminton") == 35

print('Passed storage slice test')

test_slice4 = """
def foo(inp: bytes <= 10, start: num, len: num) -> bytes <= 10:
    return slice(inp, start=start, len=len)
"""

c = s.abi_contract(test_slice4, language='viper')
assert c.foo("badminton", 3, 3) == b"min"
assert c.foo("badminton", 0, 9) == b"badminton"
assert c.foo("badminton", 1, 8) == b"adminton"
assert c.foo("badminton", 1, 7) == b"adminto"
assert c.foo("badminton", 1, 0) == b""
assert c.foo("badminton", 9, 0) == b""
try:
    c.foo("badminton", 0, 10)
    assert False
except:
    pass
try:
    c.foo("badminton", 1, 9)
    assert False
except:
    pass
try:
    c.foo("badminton", 9, 1)
    assert False
except:
    pass
try:
    c.foo("badminton", 10, 0)
    assert False
except:
    pass

print('Passed slice edge case test')

test_length = """
y: bytes <= 10
def foo(inp: bytes <= 10) -> num:
    x = slice(inp, start=1, len=5)
    self.y = slice(inp, start=2, len=4)
    return len(inp) * 100 + len(x) * 10 + len(self.y)
"""

c = s.abi_contract(test_length, language='viper')
assert c.foo("badminton") == 954, c.foo("badminton")
print('Passed length test')

test_concat = """
def foo2(input1: bytes <= 50, input2: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2)

def foo3(input1: bytes <= 50, input2: bytes <= 50, input3: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2, input3)
"""

c = s.abi_contract(test_concat, language='viper')
assert c.foo2("h", "orse") == b"horse"
assert c.foo2("h", "") == b"h"
assert c.foo2("", "") == b""
assert c.foo2("", "orse") == b"orse"
assert c.foo3("Buffalo", " ", "buffalo") == b"Buffalo buffalo"
assert c.foo2("\x36", "\x35" * 32) == b"\x36" + b"\x35" * 32
assert c.foo2("\x36" * 48, "\x35" * 32) == b"\x36" * 48 + b"\x35" * 32
assert c.foo3("horses" * 4, "mice" * 7, "crows" * 10) == b"horses" * 4 + b"mice" * 7 + b"crows" * 10
print('Passed simple concat test')

test_concat2 = """
def foo(inp: bytes <= 50) -> bytes <= 1000:
    x = inp
    return concat(x, inp, x, inp, x, inp, x, inp, x, inp)
"""

c = s.abi_contract(test_concat2, language='viper')
assert c.foo("horse" * 9 + "viper") == (b"horse" * 9 + b"viper") * 10
print('Passed second concat test')

string_literal_code = """
def foo() -> bytes <= 5:
    return "horse"

def bar() -> bytes <= 10:
    return concat("b", "a", "d", "m", "i", "", "nton")

def baz() -> bytes <= 40:
    return concat("0123456789012345678901234567890", "12")

def baz2() -> bytes <= 40:
    return concat("01234567890123456789012345678901", "12")

def baz3() -> bytes <= 40:
    return concat("0123456789012345678901234567890", "1")

def baz4() -> bytes <= 100:
    return concat("01234567890123456789012345678901234567890123456789",
                  "01234567890123456789012345678901234567890123456789")
"""

c = s.abi_contract(string_literal_code, language='viper')
assert c.foo() == b"horse"
assert c.bar() == b"badminton"
assert c.baz() == b"012345678901234567890123456789012"
assert c.baz2() == b"0123456789012345678901234567890112"
assert c.baz3() == b"01234567890123456789012345678901"
assert c.baz4() == b"0123456789" * 10

print("Passed string literal test")

for i in range(95, 96, 97):
    kode = """
def foo(s: num, L: num) -> bytes <= 100:
        x = 27
        r = slice("%s", start=s, len=L)
        y = 37
        if x * y == 999:
            return r
    """ % ("c" * i)
    c = s.abi_contract(kode, language='viper')
    for e in range(63, 64, 65):
        for _s in range(31, 32, 33):
            assert c.foo(_s, e - _s) == b"c" * (e - _s), (i, _s, e - _s, c.foo(_s, e - _s))

print("Passed string literal splicing fuzz-test")

hash_code = """
def foo(inp: bytes <= 100) -> bytes32:
    return sha3(inp)
"""

c = s.abi_contract(hash_code, language='viper')
for inp in (b"", b"cow", b"s" * 31, b"\xff" * 32, b"\n" * 33, b"g" * 64, b"h" * 65):
    assert c.foo(inp) == u.sha3(inp)

hash_code2 = """
def foo(inp: bytes <= 100) -> bool:
    return sha3(inp) == sha3("badminton")
"""
c = s.abi_contract(hash_code2, language='viper')
assert c.foo("badminto") is False
assert c.foo("badminton") is True

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
c = s.abi_contract(hash_code3, language='viper')
c.set_test("")
assert c.tryy("") is True
assert c.trymem("") is True
assert c.tryy("cow") is False
c.set_test("cow")
assert c.tryy("") is False
assert c.tryy("cow") is True
c.set_test("\x35" * 32)
assert c.tryy("\x35" * 32) is True
assert c.trymem("\x35" * 32) is True
assert c.try32(b"\x35" * 32) is True
assert c.tryy("\x35" * 33) is False
c.set_test("\x35" * 33)
assert c.tryy("\x35" * 32) is False
assert c.trymem("\x35" * 32) is False
assert c.try32(b"\x35" * 32) is False
assert c.tryy("\x35" * 33) is True

print("Passed SHA3 hash test")

ecrecover_test = """
def test_ecrecover(h: bytes32, v:num256, r:num256, s:num256) -> address:
    return ecrecover(h, v, r, s)

def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     as_num256(28),
                     as_num256(63198938615202175987747926399054383453528475999185923188997970550032613358815),
                     as_num256(6577251522710269046055727877571505144084475024240851440410274049870970796685))
"""

c = s.abi_contract(ecrecover_test, language='viper')
h = b'\x35' * 32
k = b'\x46' * 32
v, r, S = u.ecsign(h, k)
assert c.test_ecrecover(h, v, r, S) == '0x' + u.encode_hex(u.privtoaddr(k))
assert c.test_ecrecover2() == '0x' + u.encode_hex(u.privtoaddr(k))

print("Passed ecrecover test")

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

c = s.abi_contract(extract32_code, language='viper')
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

test_concat_bytes32 = """
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 164:
    return concat(inp2, inp, inp2)

def fivetimes(inp: bytes32) -> bytes <= 160:
    return concat(inp, inp, inp, inp, inp)
"""

c = s.abi_contract(test_concat_bytes32, language='viper')
assert c.sandwich("cow", b"\x35" * 32) == b"\x35" * 32 + b"cow" + b"\x35" * 32, c.sandwich("cow", b"\x35" * 32)
assert c.sandwich("", b"\x46" * 32) == b"\x46" * 64
assert c.sandwich(b"\x57" * 95, b"\x57" * 32) == b"\x57" * 159
assert c.sandwich(b"\x57" * 96, b"\x57" * 32) == b"\x57" * 160
assert c.sandwich(b"\x57" * 97, b"\x57" * 32) == b"\x57" * 161
assert c.fivetimes(b"mongoose" * 4) == b"mongoose" * 20

print("Passed concat bytes32 test")

test_wei = """
def return_2_finney() -> wei_value:
    return as_wei_value(2, finney)

def return_3_finney() -> wei_value:
    return as_wei_value(2 + 1, finney)

def return_2p5_ether() -> wei_value:
    return as_wei_value(2.5, ether)

def return_3p5_ether() -> wei_value:
    return as_wei_value(2.5 + 1, ether)

def return_2pow64_wei() -> wei_value:
    return as_wei_value(18446744.073709551616, szabo)
"""

c = s.abi_contract(test_wei, language='viper')

assert c.return_2_finney() == 2 * 10**15
assert c.return_3_finney() == 3 * 10**15, c.return_3_finney()
assert c.return_2p5_ether() == 2.5 * 10**18
assert c.return_3p5_ether() == 3.5 * 10**18
assert c.return_2pow64_wei() == 2**64

print("Passed wei value literals test")

caller_code = """
def foo() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=5)

def bar() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=3)

def baz() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=7)
"""

c = s.abi_contract(caller_code, language='viper')
assert c.foo() == b"moose"
assert c.bar() == b"moo"
assert c.baz() == b"moose\x00\x00"

print('Passed raw call test')

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

c = s.abi_contract(extract32_code, language='viper')
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

bytes_to_num_code = """
def foo(x: bytes <= 32) -> num:
    return bytes_to_num(x)
"""

c = s.abi_contract(bytes_to_num_code, language='viper')
assert c.foo(b"") == 0
try:
    c.foo(b"\x00")
    success = True
except:
    success = False
assert not success
assert c.foo(b"\x01") == 1
try:
    c.foo(b"\x00\x01")
    success = True
except:
    success = False
assert not success
assert c.foo(b"\x01\x00") == 256
assert c.foo(b"\x01\x00\x00\x00\x01") == 4294967297
assert c.foo(b"\xff" * 32) == -1
try:
    c.foo(b"\x80" + b"\xff" * 31)
    success = True
except:
    success = False
try:
    c.foo(b"\x01" * 33)
    success = True
except:
    success = False
print('Passed bytes_to_num tests')

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
"""
c = s.abi_contract(rlp_decoder_code, language='viper')

assert c.foo() == '0x' + '35' * 20
assert c.fop() == b'G' * 32
assert c.foq() == b'cow'
assert c.fos() == 3
assert c.fot() == 3
assert c.qoo(b'\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG') == '0x' + '35' * 20
assert c.roo(b'\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG') == '0x' + '35' * 20
assert c.qos(rlp.encode([3, 30])) == 33
assert c.qos(rlp.encode([3, 2**100 - 5])) == 2**100 - 2
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

print('Passed RLP decoder tests')

getter_code = """
x: public(num)
y: public(num[5])
z: public(bytes <= 100)
w: public({
    a: num,
    b: num[7],
    c: bytes <= 100,
    d: num[address],
    e: num[3][3]
}[5])

def __init__():
    self.x = 7
    self.y[1] = 9
    self.z = "cow"
    self.w[1].a = 11
    self.w[1].b[2] = 13
    self.w[1].c = "horse"
    self.w[1].d[0x1234567890123456789012345678901234567890] = 15
    self.w[2].e[1][2] = 17
"""

c = s.abi_contract(getter_code, language='viper')
assert c.get_x() == 7
assert c.get_y(1) == 9
assert c.get_z() == b"cow"
assert c.get_w__a(1) == 11
assert c.get_w__b(1, 2) == 13
assert c.get_w__c(1) == b"horse"
assert c.get_w__d(1, "0x1234567890123456789012345678901234567890") == 15
assert c.get_w__e(2, 1, 2) == 17

print('Passed getter tests')
