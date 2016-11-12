import parser, compile_lll
import compiler_plugin
from ethereum import tester as t
# from ethereum.slogging import LogRecorder, configure_logging, set_level
# config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
# configure_logging(config_string=config_string)

s = t.state()
t.languages['viper'] = compiler_plugin.Compiler() 

basic_code = """

def foo(x: num) -> num:
    return x * 2

"""

c = s.abi_contract(basic_code, language='viper')
assert c.foo(9) == 18
print('Passed basic code test')
print('Gas estimate', t.languages['viper'].gas_estimate(basic_code)['foo'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

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
print('Gas estimate', t.languages['viper'].gas_estimate(basic_repeater)['repeat'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

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
print('Gas estimate', t.languages['viper'].gas_estimate(more_complex_repeater)['repeat'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

array_accessor = """
def test_array(x: num, y: num, z: num, w: num) -> num:
    a = num[4]
    a[0] = x
    a[1] = y
    a[2] = z
    a[3] = w
    return a[0] * 1000 + a[1] * 100 + a[2] * 10 + a[3]
"""

c = s.abi_contract(array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed basic array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(array_accessor)['test_array'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

two_d_array_accessor = """
def test_array(x: num, y: num, z: num, w: num) -> num:
    a = num[2][2]
    a[0][0] = x
    a[0][1] = y
    a[1][0] = z
    a[1][1] = w
    return a[0][0] * 1000 + a[0][1] * 100 + a[1][0] * 10 + a[1][1]
"""

c = s.abi_contract(two_d_array_accessor, language='viper')
assert c.test_array(2, 7, 1, 8) == 2718
print('Passed complex array accessor test')
print('Gas estimate', t.languages['viper'].gas_estimate(two_d_array_accessor)['test_array'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)


digit_reverser = """

def reverse_digits(x: num) -> num:
    dig = num[6]
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
print('Gas estimate', t.languages['viper'].gas_estimate(digit_reverser)['reverse_digits'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

arbitration_code = """
buyer = address
seller = address
arbitrator = address

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

c = s.abi_contract(arbitration_code, language='viper')
c.setup(t.a1, t.a2, sender=t.k0)
try:
    c.finalize(sender=t.k1)
    success = True
except t.TransactionFailed:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

arbitration_code_with_init = """
buyer = address
seller = address
arbitrator = address

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

c = s.abi_contract(arbitration_code_with_init, language='viper', constructor_parameters=[t.a1, t.a2], sender=t.k0)
try:
    c.finalize(sender=t.k1)
    success = True
except t.TransactionFailed:
    success = False
assert not success
c.finalize(sender=t.k0)

print('Passed escrow test with initializer')
print('Gas estimate', t.languages['viper'].gas_estimate(arbitration_code)['finalize'], 'actual', s.state.receipts[-1].gas_used - s.state.receipts[-2].gas_used - 21000)

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
print('Gas estimate', sum(estimate.values()), 'actual', post_gas - pre_gas - 21000 * (post_txs - pre_txs))

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
moose = num
def __init__(_moose: num):
    self.moose = _moose

def returnMoose() -> num:
    return self.moose
"""

c = s.abi_contract(init_argument_test, language='viper', constructor_parameters=[5])
assert c.returnMoose() == 5
print('Passed init argument test')

permanent_variables_test = """
var = [a(num), b(num)]
def __init__(a: num, b: num):
    self.var.a = a
    self.var.b = b

def returnMoose() -> num:
    return self.var.a * 10 + self.var.b
"""

c = s.abi_contract(permanent_variables_test, language='viper', constructor_parameters=[5, 7])
assert c.returnMoose() == 57
print('Passed init argument and variable member test')


crowdfund = """

funders = {num: [sender(address), value(num)]}
nextFunderIndex = num
beneficiary = address
deadline = num
goal = num
refundIndex = num
timelimit = num

def __init__(_beneficiary: address, _goal: num, _timelimit: num):
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

def timestamp() -> num(const):
    return block.timestamp

def deadline() -> num(const):
    return self.deadline

def timelimit() -> num(const):
    return self.timelimit

def reached() -> bool(const):
    return self.balance >= self.goal

def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal
    selfdestruct(self.beneficiary)

def refund():
    ind = self.refundIndex
    for i in range(30):
        if ind + i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return
        send(self.funders[ind + i].sender, self.funders[ind + i].value)
        self.funders[ind + i].sender = "0x0000000000000000000000000000000000000000"
        self.funders[ind + i].value = 0
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
