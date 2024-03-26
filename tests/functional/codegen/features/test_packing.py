def test_packing_test(get_contract_with_gas_estimation, memory_mocker):
    packing_test = """
struct Bar:
    a: int128
    b: int128
struct Z:
    foo: int128[3]
    bar: Bar[2]
x: int128
y: int128[5]
z: Z
a: int128

@external
def foo() -> int128:
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

@external
def fop() -> int128:
    _x: int128 = 0
    _y: int128[5] = [0, 0, 0, 0, 0]
    _z: Z = Z(foo=[0, 0, 0], bar=[Bar(a=0, b=0), Bar(a=0, b=0)])
    _a: int128 = 0
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
    print("Passed packing test")
