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
