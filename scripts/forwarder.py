from ethereum import utils


def mk_forwarder(address):
    code = b'\x36\x60\x00\x60\x00\x37'  # CALLDATACOPY 0 0 (CALLDATASIZE)
    code += b'\x61\x10\x00\x60\x00\x36\x60\x00'  # 4096 0 CALLDATASIZE 0
    code += b'\x73' + utils.normalize_address(address) + b'\x5a'  # address gas
    code += b'\xf4'  # delegatecall
    code += b'\x15\x58\x57'  # ISZERO PC JUMPI (fail if inner call fails)
    code += b'\x61\x10\x00\x60\x00\xf3'  # 4096 0 RETURN
    return code


def mk_wrapper(code):
    lencodepush = b'\x60' + utils.encode_int(len(code))  # length of code
    returner = lencodepush + b'\x60\x0c\x60\x00'  # start from 12 in code, 0 in memory
    returner += b'\x39'  # CODECOPY
    returner += lencodepush + b'\x60\x00' + b'\xf3'  # return code
    assert len(returner) == 12
    return returner + code


kode = """
moose: num
def increment_moose(i: num) -> num:
    self.moose += i
    return self.moose
"""


def test():
    from ethereum.tools import tester2
    c = tester2.Chain()
    x = c.contract(kode, language='vyper', sender=tester2.k3)
    fwdcode = mk_forwarder(x.address)
    initcode = mk_wrapper(fwdcode)
    print('Forwarder code:', initcode)
    y = c.contract(initcode, language='evm')
    assert c.head_state.get_code(y) == fwdcode
    z = tester2.ABIContract(c, x.translator, y)
    assert z.increment_moose(3) == 3
    assert z.increment_moose(5) == 8
    print('Tests passed')


if __name__ == '__main__':
    test()
