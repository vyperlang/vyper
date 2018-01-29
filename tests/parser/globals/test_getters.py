def test_state_accessor(get_contract_with_gas_estimation_for_constants):
    state_accessor = """
y: num[num]

@public
def oo():
    self.y[3] = 5

@public
def foo() -> num:
    return self.y[3]

    """

    c = get_contract_with_gas_estimation_for_constants(state_accessor)
    c.oo()
    assert c.foo() == 5
    print('Passed basic state accessor test')


def test_getter_code(get_contract_with_gas_estimation_for_constants):
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

@public
def __init__():
    self.x = as_wei_value(7, "wei")
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

    c = get_contract_with_gas_estimation_for_constants(getter_code)
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
