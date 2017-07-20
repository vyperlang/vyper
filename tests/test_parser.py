from viper import parser, compile_lll, utils
from viper import compiler
from ethereum.tools import tester2 as t
from ethereum import transactions, messages
from ethereum import utils as u
import rlp
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
#configure_logging(config_string=config_string)

s = t.Chain()
t.languages['viper'] = compiler.Compiler() 

def inject_tx(txhex):
    tx = rlp.decode(u.decode_hex(txhex[2:]), transactions.Transaction)
    s.head_state.set_balance(tx.sender, tx.startgas * tx.gasprice)
    s.chain.state.set_balance(tx.sender, tx.startgas * tx.gasprice)
    messages.apply_transaction(s.head_state, tx)
    s.block.transactions.append(tx)
    contract_address = u.sha3(rlp.encode([tx.sender, 0]))[12:]
    assert s.head_state.get_code(contract_address)
    s.mine(1)
    return contract_address

rlp_decoder_address = inject_tx( "0xf90237808506fc23ac00830330888080b902246102128061000e60003961022056600060007f010000000000000000000000000000000000000000000000000000000000000060003504600060c082121515585760f882121561004d5760bf820336141558576001905061006e565b600181013560f783036020035260005160f6830301361415585760f6820390505b5b368112156101c2577f010000000000000000000000000000000000000000000000000000000000000081350483602086026040015260018501945060808112156100d55760018461044001526001828561046001376001820191506021840193506101bc565b60b881121561014357608081038461044001526080810360018301856104600137608181141561012e5760807f010000000000000000000000000000000000000000000000000000000000000060018401350412151558575b607f81038201915060608103840193506101bb565b60c08112156101b857600182013560b782036020035260005160388112157f010000000000000000000000000000000000000000000000000000000000000060018501350402155857808561044001528060b6838501038661046001378060b6830301830192506020810185019450506101ba565bfe5b5b5b5061006f565b601f841315155857602060208502016020810391505b6000821215156101fc578082604001510182826104400301526020820391506101d8565b808401610420528381018161044003f350505050505b6000f31b2d4f")
assert utils.bytes_to_int(rlp_decoder_address) == utils.RLP_DECODER_ADDRESS

s.head_state.gas_limit = 10**9


null_code = """
def foo():
    pass
"""

c = s.contract(null_code, language='viper')
c.foo()

print('Successfully executed a null function')
print('Gas estimate', t.languages['viper'].gas_estimate(null_code)['foo'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

basic_code = """

def foo(x: num) -> num:
    return x * 2

"""

c = s.contract(basic_code, language='viper')
assert c.foo(9) == 18
print('Passed basic code test')
print('Gas estimate', t.languages['viper'].gas_estimate(basic_code)['foo'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

basic_repeater = """

def repeat(z: num) -> num:
    x = 0
    for i in range(6):
        x = x + z
    return(x)
"""

c = s.contract(basic_repeater, language='viper')
assert c.repeat(9) == 54
print('Passed basic repeater test')
print('Gas estimate', t.languages['viper'].gas_estimate(basic_repeater)['repeat'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

more_complex_repeater = """
def repeat() -> num:
    out = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
"""


c = s.contract(more_complex_repeater, language='viper')
assert c.repeat() == 666666
print('Passed complex repeater test')
print('Gas estimate', t.languages['viper'].gas_estimate(more_complex_repeater)['repeat'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

offset_repeater = """
def sum() -> num:
    out = 0
    for i in range(80, 121):
        out = out + i
    return(out)
"""

c = s.contract(offset_repeater, language='viper')
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

c = s.contract(offset_repeater_2, language='viper')
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

c = s.contract(array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed basic array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(array_accessor)['test_array'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

two_d_array_accessor = """
def test_array(x: num, y: num, z: num, w: num) -> num:
    a: num[2][2]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
"""

c = s.contract(two_d_array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed complex array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(two_d_array_accessor)['test_array'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)


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

c = s.contract(digit_reverser, language='viper')
assert c.reverse_digits(123456) == 654321
print('Passed digit reverser test')
print('Gas estimate', t.languages['viper'].gas_estimate(digit_reverser)['reverse_digits'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

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

c = s.contract(arbitration_code, language='viper', value=1)
c.setup(t.a1, t.a2, sender=t.k0)
try:
    c.finalize(sender=t.k1)
    success = True
except:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

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

c = s.contract(arbitration_code_with_init, language='viper', args=[t.a1, t.a2], sender=t.k0, value=1)
try:
    c.finalize(sender=t.k1)
    success = True
except t.TransactionFailed:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test with initializer')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

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

c = s.contract(decimal_test, language='viper')
pre_gas = s.head_state.receipts[-1].gas_used
pre_txs = len(s.head_state.receipts)
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
post_gas = s.head_state.receipts[-1].gas_used
post_txs = len(s.head_state.receipts)

estimate = t.languages['viper'].gas_estimate(decimal_test)


print('Passed basic addition, subtraction and multiplication tests')
print('Gas estimate', sum(estimate.values()), 'actual', post_gas - pre_gas - s.last_tx.intrinsic_gas_used * (post_txs - pre_txs))

harder_decimal_test = """
def phooey(inp: decimal) -> decimal:
    x = 10000.0
    for i in range(4):
        x = x * inp
    return x

def arg(inp: decimal) -> decimal:
    return inp

def garg() -> decimal:
    x = 4.5
    x *= 1.5
    return x

def harg() -> decimal:
    x = 4.5
    x *= 2
    return x

def iarg() -> wei_value:
    x = as_wei_value(7, wei)
    x *= 2
    return x
"""


c = s.contract(harder_decimal_test, language='viper')
assert c.phooey(1.2) == 20736.0
assert c.phooey(-1.2) == 20736.0
assert c.arg(-3.7) == -3.7
assert c.arg(3.7) == 3.7
assert c.garg() == 6.75
assert c.harg() == 9.0
assert c.iarg() == 14

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

c = s.contract(break_test, language='viper')
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


c = s.contract(break_test_2, language='viper')
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

c = s.contract(augassign_test, language='viper')

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
c = s.contract(break_test_3, language='viper')
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

c = s.contract(init_argument_test, language='viper', args=[5])
assert c.returnMoose() == 5
print('Passed init argument test')
print('Gas estimate', t.languages['viper'].gas_estimate(init_argument_test)['returnMoose'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)

constructor_advanced_code = """
twox: num

def __init__(x: num):
    self.twox = x * 2

def get_twox() -> num:
    return self.twox
"""
assert s.contract(constructor_advanced_code, args=[5], language='viper').get_twox() == 10

constructor_advanced_code2 = """
comb: num

def __init__(x: num[2], y: bytes <= 3, z: num):
    self.comb = x[0] * 1000 + x[1] * 100 + len(y) * 10 + z

def get_comb() -> num:
    return self.comb
"""
assert s.contract(constructor_advanced_code2, args=[[5,7], "dog", 8], language='viper').get_comb() == 5738

print("Passed advanced init argument tests")

permanent_variables_test = """
var: {a: num, b: num}
def __init__(a: num, b: num):
    self.var.a = a
    self.var.b = b

def returnMoose() -> num:
    return self.var.a * 10 + self.var.b
"""

c = s.contract(permanent_variables_test, language='viper', args=[5, 7])
assert c.returnMoose() == 57
print('Passed init argument and variable member test')
print('Gas estimate', t.languages['viper'].gas_estimate(permanent_variables_test)['returnMoose'], 'actual', s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used)


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

c = s.contract(crowdfund, language='viper', args=[t.a1, 50, 600])


c.participate(value = 5)
assert c.timelimit() == 600
assert c.deadline() - c.timestamp() == 600
assert not c.expired()
assert not c.reached()
c.participate(value = 49)
assert c.reached()
pre_bal = s.head_state.get_balance(t.a1)
s.head_state.timestamp += 1000
assert c.expired()
c.finalize()
post_bal = s.head_state.get_balance(t.a1)
assert post_bal - pre_bal == 54

c = s.contract(crowdfund, language='viper', args=[t.a1, 50, 600])
c.participate(value = 1, sender=t.k3)
c.participate(value = 2, sender=t.k4)
c.participate(value = 3, sender=t.k5)
c.participate(value = 4, sender=t.k6)
s.head_state.timestamp += 1000
assert c.expired()
assert not c.reached()
pre_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
c.refund()
post_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
assert [y-x for x, y in zip(pre_bals, post_bals)] == [1,2,3,4]

print('Passed composite crowdfund test')

comment_test = """

def foo() -> num:
    # Returns 3
    return 3
"""

c = s.contract(comment_test, language='viper')
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

c = s.contract(packing_test, language='viper')
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

c = s.contract(multi_setter_test, language='viper')
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

c = s.contract(multi_setter_struct_test, language='viper')
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

c = s.contract(type_converter_setter_test, language='viper')
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

c = s.contract(composite_setter_test, language='viper')
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

c = s.contract(crowdfund2, language='viper', args=[t.a1, 50, 600])


c.participate(value = 5)
assert c.timelimit() == 600
assert c.deadline() - c.timestamp() == 600
assert not c.expired()
assert not c.reached()
c.participate(value = 49)
assert c.reached()
pre_bal = s.head_state.get_balance(t.a1)
s.head_state.timestamp += 1000
assert c.expired()
c.finalize()
post_bal = s.head_state.get_balance(t.a1)
assert post_bal - pre_bal == 54

c = s.contract(crowdfund2, language='viper', args=[t.a1, 50, 600])
c.participate(value = 1, sender=t.k3)
c.participate(value = 2, sender=t.k4)
c.participate(value = 3, sender=t.k5)
c.participate(value = 4, sender=t.k6)
s.head_state.timestamp += 1000
assert c.expired()
assert not c.reached()
pre_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
c.refund()
post_bals = [s.head_state.get_balance(x) for x in [t.a3, t.a4, t.a5, t.a6]]
assert [y-x for x, y in zip(pre_bals, post_bals)] == [1,2,3,4]

print('Passed second composite crowdfund test')

test_bytes = """
def foo(x: bytes <= 100) -> bytes <= 100:
    return x
"""

c = s.contract(test_bytes, language='viper')
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

c = s.contract(test_bytes2, language='viper')
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

c = s.contract(test_bytes3, language='viper')
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

c = s.contract(test_bytes4, language='viper')
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

c = s.contract(test_bytes5, language='viper')
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

c = s.contract(test_slice, language='viper')
x = c.foo(b"badminton")
assert x == b"min", x

assert c.bar(b"badminton") == 35

print('Passed slice test')

test_slice2 = """
def slice_tower_test(inp1: bytes <= 50) -> bytes <= 50:
    inp = inp1
    for i in range(1, 11):
        inp = slice(inp, start=1, len=30 - i * 2)
    return inp
"""

c = s.contract(test_slice2, language='viper')
x = c.slice_tower_test(b"abcdefghijklmnopqrstuvwxyz1234")
assert x == b"klmnopqrst", x

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

c = s.contract(test_slice3, language='viper')
x = c.foo(b"badminton")
assert x == b"min", x

assert c.bar(b"badminton") == 35

print('Passed storage slice test')

test_slice4 = """
def foo(inp: bytes <= 10, start: num, len: num) -> bytes <= 10:
    return slice(inp, start=start, len=len)
"""

c = s.contract(test_slice4, language='viper')
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

test_length = """
y: bytes <= 10
def foo(inp: bytes <= 10) -> num:
    x = slice(inp, start=1, len=5)
    self.y = slice(inp, start=2, len=4)
    return len(inp) * 100 + len(x) * 10 + len(self.y)
"""

c = s.contract(test_length, language='viper')
assert c.foo(b"badminton") == 954, c.foo(b"badminton")
print('Passed length test')

test_concat = """
def foo2(input1: bytes <= 50, input2: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2)

def foo3(input1: bytes <= 50, input2: bytes <= 50, input3: bytes <= 50) -> bytes <= 1000:
    return concat(input1, input2, input3)
"""

c = s.contract(test_concat, language='viper')
assert c.foo2(b"h", b"orse") == b"horse"
assert c.foo2(b"h", b"") == b"h"
assert c.foo2(b"", b"") == b""
assert c.foo2(b"", b"orse") == b"orse"
assert c.foo3(b"Buffalo", b" ", b"buffalo") == b"Buffalo buffalo"
assert c.foo2(b"\x36", b"\x35" * 32) == b"\x36" + b"\x35" * 32
assert c.foo2(b"\x36" * 48, b"\x35" * 32) == b"\x36" * 48 + b"\x35" * 32
assert c.foo3(b"horses" * 4, b"mice" * 7, b"crows" * 10) == b"horses" * 4 + b"mice" * 7 + b"crows" * 10
print('Passed simple concat test')

test_concat2 = """
def foo(inp: bytes <= 50) -> bytes <= 1000:
    x = inp
    return concat(x, inp, x, inp, x, inp, x, inp, x, inp)
"""

c = s.contract(test_concat2, language='viper')
assert c.foo(b"horse" * 9 + b"viper") == (b"horse" * 9 + b"viper") * 10
print('Passed second concat test')

crazy_concat_code = """
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 25:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
"""

c = s.contract(crazy_concat_code, language='viper')

assert c.krazykonkat(b"moose") == b'cow horse moose'

print('Passed third concat test')

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

c = s.contract(string_literal_code, language='viper')
assert c.foo() == b"horse"
assert c.bar() == b"badminton"
assert c.baz() == b"012345678901234567890123456789012"
assert c.baz2() == b"0123456789012345678901234567890112"
assert c.baz3() == b"01234567890123456789012345678901"
assert c.baz4() == b"0123456789" * 10

print("Passed string literal test")

for i in range(95, 96, 97):
    kode = """
moo: bytes <= 100

def foo(s: num, L: num) -> bytes <= 100:
        x = 27
        r = slice("%s", start=s, len=L)
        y = 37
        if x * y == 999:
            return r

def bar(s: num, L: num) -> bytes <= 100:
        self.moo = "%s"
        x = 27
        r = slice(self.moo, start=s, len=L)
        y = 37
        if x * y == 999:
            return r

def baz(s: num, L: num) -> bytes <= 100:
        x = 27
        self.moo = slice("%s", start=s, len=L)
        y = 37
        if x * y == 999:
            return self.moo
    """ % (("c" * i), ("c" * i), ("c" * i))
    c = s.contract(kode, language='viper')
    for e in range(63, 64, 65):
        for _s in range(31, 32, 33):
            #print(parser.parse_tree_to_lll(parser.parse(kode), kode))
            #configure_logging(config_string=config_string)
            o1 = c.foo(_s, e - _s)
            o2 = c.bar(_s, e - _s)
            o3 = c.baz(_s, e - _s)
            assert o1 == o2 == o3 == b"c" * (e - _s), (i, _s, e - _s, o1, o2, o3) 

print("Passed string literal splicing fuzz-test")

hash_code = """
def foo(inp: bytes <= 100) -> bytes32:
    return sha3(inp)

def bar() -> bytes32:
    return sha3("inp")
"""

c = s.contract(hash_code, language='viper')
for inp in (b"", b"cow", b"s" * 31, b"\xff" * 32, b"\n" * 33, b"g" * 64, b"h" * 65):
    assert c.foo(inp) == u.sha3(inp)

assert c.bar() == u.sha3("inp")

hash_code2 = """
def foo(inp: bytes <= 100) -> bool:
    return sha3(inp) == sha3("badminton")
"""
c = s.contract(hash_code2, language='viper')
assert c.foo(b"badminto") is False
assert c.foo(b"badminton") is True

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
c = s.contract(hash_code3, language='viper')
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

method_id_test = """
def double(x: num) -> num:
    return x * 2

def returnten() -> num:
    ans = raw_call(self, concat(method_id("double(int128)"), as_bytes32(5)), gas=50000, outsize=32)
    return as_num128(extract32(ans, 0))
"""
c = s.contract(method_id_test, language='viper')
assert c.returnten() == 10
print("Passed method ID test")

ecrecover_test = """
def test_ecrecover(h: bytes32, v:num256, r:num256, s:num256) -> address:
    return ecrecover(h, v, r, s)

def test_ecrecover2() -> address:
    return ecrecover(0x3535353535353535353535353535353535353535353535353535353535353535,
                     as_num256(28),
                     as_num256(63198938615202175987747926399054383453528475999185923188997970550032613358815),
                     as_num256(6577251522710269046055727877571505144084475024240851440410274049870970796685))
"""

c = s.contract(ecrecover_test, language='viper')
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

c = s.contract(extract32_code, language='viper')
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

c = s.contract(test_concat_bytes32, language='viper')
assert c.sandwich(b"cow", b"\x35" * 32) == b"\x35" * 32 + b"cow" + b"\x35" * 32, c.sandwich(b"cow", b"\x35" * 32)
assert c.sandwich(b"", b"\x46" * 32) == b"\x46" * 64
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

c = s.contract(test_wei, language='viper')

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

c = s.contract(caller_code, language='viper')
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

c = s.contract(extract32_code, language='viper')
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

c = s.contract(bytes_to_num_code, language='viper')
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

def too(inp: bytes <= 100) -> bool:
    x = RLPList(inp, [bool])
    return x[0]
"""
c = s.contract(rlp_decoder_code, language='viper')

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

c = s.contract(getter_code, language='viper')
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

c = s.contract(konkat_code, language='viper')
assert c.foo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32
assert c.goo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32
assert c.hoo(b'\x35' * 32, b'\x00' * 32) == b'\x35' * 32 + b'\x00' * 32

print('Passed second concat tests')

conditional_return_code = """
def foo(i: bool) -> num:
    if i:
        return 5
    else:
        assert 2
        return 7
    return 11
"""

c = s.contract(conditional_return_code, language='viper')
assert c.foo(True) == 5
assert c.foo(False) == 7

print('Passed conditional return tests')

large_input_code = """
def foo(x: num) -> num:
    return 3
"""

c = s.contract(large_input_code, language='viper')
c.foo(1274124)
c.foo(2**120)
try:
    c.foo(2**130)
    success = True
except:
    success = False
assert not success

large_input_code_2 = """
def __init__(x: num):
    y = x

def foo() -> num:
    return 5
"""

c = s.contract(large_input_code_2, language='viper', args=[17], sender=t.k0, value=0)
try:
    c = s.contract(large_input_code_2, language='viper', args=[2**130], sender=t.k0, value=0)
    success = True
except:
    success = False
assert not success

print('Passed invalid input tests')

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

c = s.contract(loggy_code, language='viper')
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

c = s.contract(test_bitwise, language='viper')
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

num256_code = """
def _num256_add(x: num256, y: num256) -> num256:
    return num256_add(x, y)

def _num256_sub(x: num256, y: num256) -> num256:
    return num256_sub(x, y)

def _num256_mul(x: num256, y: num256) -> num256:
    return num256_mul(x, y)

def _num256_div(x: num256, y: num256) -> num256:
    return num256_div(x, y)

def _num256_gt(x: num256, y: num256) -> bool:
    return num256_gt(x, y)

def _num256_ge(x: num256, y: num256) -> bool:
    return num256_ge(x, y)

def _num256_lt(x: num256, y: num256) -> bool:
    return num256_lt(x, y)

def _num256_le(x: num256, y: num256) -> bool:
    return num256_le(x, y)
"""

c = s.contract(num256_code, language='viper')
x = 126416208461208640982146408124
y = 7128468721412412459

assert c._num256_add(x, y) == x + y
assert c._num256_sub(x, y) == x - y
assert c._num256_sub(y, x) == 2**256 + y - x
assert c._num256_mul(x, y) == x * y
assert c._num256_mul(2**128, 2**128) == 0
assert c._num256_div(x, y) == x // y
assert c._num256_div(y, x) == 0
assert c._num256_gt(x, y) is True
assert c._num256_ge(x, y) is True
assert c._num256_le(x, y) is False
assert c._num256_lt(x, y) is False
assert c._num256_gt(x, x) is False
assert c._num256_ge(x, x) is True
assert c._num256_le(x, x) is True
assert c._num256_lt(x, x) is False
assert c._num256_lt(y, x) is True

print("Passed num256 operation tests")

selfcall_code = """
def foo() -> num:
    return 3

def bar() -> num:
    return self.foo()
"""

c = s.contract(selfcall_code, language='viper')
assert c.bar() == 3

print("Passed no-argument self-call test")

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

c = s.contract(selfcall_code_2, language='viper')
assert c.returnten() == 10
assert c.return_hash_of_rzpadded_cow() == u.sha3(b'cow' + b'\x00' * 29)

print("Passed single fixed-size argument self-call test")

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

c = s.contract(selfcall_code_3, language='viper')
assert c.return_hash_of_cow_x_30() == u.sha3(b'cow' * 30)
assert c.returnten() == 10

print("Passed single variable-size argument self-call test")

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

c = s.contract(selfcall_code_4, language='viper')
assert c.returnten() == 10
assert c.return_mongoose() == b"mongoose"
assert c.return_goose() == b"goose"
assert c.return_goose2() == b"goose"

print("Passed multi-argument self-call test")

selfcall_code_5 = """
counter: num

def increment():
    self.counter += 1

def returnten() -> num:
    for i in range(10):
        self.increment()
    return self.counter
"""
c = s.contract(selfcall_code_5, language='viper')
assert c.returnten() == 10

print("Passed self-call statement test")

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

c = s.contract(selfcall_code_6, language='viper')
assert c.return_mongoose_revolution_32_excls() == b"mongoose_revolution" + b"!" * 32

print("Passed composite self-call test")

clamper_test_code = """
def foo(s: bytes <= 3) -> bytes <= 3:
    return s
"""

c = s.contract(clamper_test_code, language='viper', value=1)
assert c.foo(b"ca") == b"ca"
assert c.foo(b"cat") == b"cat"
try:
    c.foo(b"cate")
    success = True
except t.TransactionFailed:
    success = False
assert not success

print("Passed bytearray clamping test")

inner_code = """
def returnten() -> num:
    return 10
"""

c = s.contract(inner_code, language='viper')


outer_code = """
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
"""

c2 = s.contract(outer_code, language='viper')
assert c2.create_and_call_returnten(c.address) == 10
expected_forwarder_code_mask = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'[12:]
c3 = c2.create_and_return_forwarder(c.address)
assert s.head_state.get_code(c3)[:15] == expected_forwarder_code_mask[:15]
assert s.head_state.get_code(c3)[35:] == expected_forwarder_code_mask[35:]

print('Passed forwarder test')
print('Gas consumed: %d' % (s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used))

inner_code = """
def returnten() -> num:
    assert False
    return 10
"""

c = s.contract(inner_code, language='viper')


outer_code = """
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
"""

c2 = s.contract(outer_code, language='viper')
try:
    c2.create_and_call_returnten(c.address)
    success = True
except:
    success = False
assert not success

print('Passed forwarder exception test')

list_tester_code = """
z: num[3]
z2: num[2][2]
z3: num[2]

def foo(x: num[3]) -> num:
    return x[0] + x[1] + x[2]

def goo(x: num[2][2]) -> num:
    return x[0][0] + x[0][1] + x[1][0] * 10 + x[1][1] * 10

def hoo(x: num[3]) -> num:
    y = x
    return y[0] + x[1] + y[2]

def joo(x: num[2][2]) -> num:
    y = x
    y2 = x[1]
    return y[0][0] + y[0][1] + y2[0] * 10 + y2[1] * 10

def koo(x: num[3]) -> num:
    self.z = x
    return self.z[0] + x[1] + self.z[2]

def loo(x: num[2][2]) -> num:
    self.z2 = x
    self.z3 = x[1]
    return self.z2[0][0] + self.z2[0][1] + self.z3[0] * 10 + self.z3[1] * 10
"""

c = s.contract(list_tester_code, language='viper')
assert c.foo([3,4,5]) == 12
assert c.goo([[1,2],[3,4]]) == 73
assert c.hoo([3,4,5]) == 12
assert c.joo([[1,2],[3,4]]) == 73
assert c.koo([3,4,5]) == 12
assert c.loo([[1,2],[3,4]]) == 73
print("Passed list tests")

list_output_tester_code = """
z: num[2]

def foo() -> num[2]:
    return [3, 5]

def goo() -> num[2]:
    x = [3, 5]
    return x

def hoo() -> num[2]:
    self.z = [3, 5]
    return self.z

def joo() -> num[2]:
    self.z = [3, 5]
    x = self.z
    return x

def koo() -> num[2][2]:
    return [[1,2],[3,4]]

def loo() -> num[2][2]:
    x = [[1,2],[3,4]]
    return x

def moo() -> num[2][2]:
    x = [1,2]
    return [x,[3,4]]

def noo(inp: num[2]) -> num[2]:
    return inp

def poo(inp: num[2][2]) -> num[2][2]:
    return inp

def qoo(inp: num[2]) -> num[2][2]:
    return [inp,[3,4]]

def roo(inp: num[2]) -> decimal[2][2]:
    return [inp,[3,4]]
"""

c = s.contract(list_output_tester_code, language='viper')
assert c.foo() == [3,5]
assert c.goo() == [3,5]
assert c.hoo() == [3,5]
assert c.joo() == [3,5]
assert c.koo() == [[1,2],[3,4]]
assert c.loo() == [[1,2],[3,4]]
assert c.moo() == [[1,2],[3,4]]
assert c.noo([3,5]) == [3,5]
assert c.poo([[1,2],[3,4]]) == [[1,2],[3,4]]
assert c.qoo([1,2]) == [[1,2],[3,4]]
assert c.roo([1,2]) == [[1.0,2.0],[3.0,4.0]]

print("Passed list output tests")
