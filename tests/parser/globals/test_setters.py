def test_multi_setter_test(get_contract_with_gas_estimation):
    multi_setter_test = """
foo: num[3]
bar: num[3][3]
@public
def foo() -> num:
    self.foo = [1, 2, 3]
    return(self.foo[0] + self.foo[1] * 10 + self.foo[2] * 100)

@public
def fop() -> num:
    self.bar[0] = [1, 2, 3]
    self.bar[1] = [4, 5, 6]
    return self.bar[0][0] + self.bar[0][1] * 10 + self.bar[0][2] * 100 + \
        self.bar[1][0] * 1000 + self.bar[1][1] * 10000 + self.bar[1][2] * 100000

@public
def goo() -> num:
    goo: num[3]
    goo = [1, 2, 3]
    return(goo[0] + goo[1] * 10 + goo[2] * 100)

@public
def gop() -> num: # Following a standard naming scheme; nothing to do with the US republican party
    gar: num[3][3]
    gar[0] = [1, 2, 3]
    gar[1] = [4, 5, 6]
    return gar[0][0] + gar[0][1] * 10 + gar[0][2] * 100 + \
        gar[1][0] * 1000 + gar[1][1] * 10000 + gar[1][2] * 100000

@public
def hoo() -> num:
    self.foo = None
    return(self.foo[0] + self.foo[1] * 10 + self.foo[2] * 100)

@public
def hop() -> num:
    self.bar[1] = None
    return self.bar[0][0] + self.bar[0][1] * 10 + self.bar[0][2] * 100 + \
        self.bar[1][0] * 1000 + self.bar[1][1] * 10000 + self.bar[1][2] * 100000

@public
def joo() -> num:
    goo: num[3]
    goo = [1, 2, 3]
    goo = None
    return(goo[0] + goo[1] * 10 + goo[2] * 100)

@public
def jop() -> num:
    gar: num[3][3]
    gar[0] = [1, 2, 3]
    gar[1] = [4, 5, 6]
    gar[1] = None
    return gar[0][0] + gar[0][1] * 10 + gar[0][2] * 100 + \
        gar[1][0] * 1000 + gar[1][1] * 10000 + gar[1][2] * 100000

    """

    c = get_contract_with_gas_estimation(multi_setter_test)
    assert c.foo() == 321
    assert c.fop() == 654321
    assert c.goo() == 321
    assert c.gop() == 654321
    assert c.hoo() == 0
    assert c.hop() == 321
    assert c.joo() == 0
    assert c.jop() == 321
    print('Passed multi-setter literal test')


def test_multi_setter_struct_test(get_contract_with_gas_estimation):
    multi_setter_struct_test = """
foo: {foo: num, bar: num}[3]
z: {foo: num[3], bar: {a: num, b: num}[2]}[2]

@public
def foo() -> num:
    self.foo[0] = {foo: 1, bar: 2}
    self.foo[1] = {foo: 3, bar: 4}
    self.foo[2] = {foo: 5, bar: 6}
    return self.foo[0].foo + self.foo[0].bar * 10 + self.foo[1].foo * 100 + \
        self.foo[1].bar * 1000 + self.foo[2].foo * 10000 + self.foo[2].bar * 100000

@public
def fop() -> num:
    self.z = [{foo: [1, 2, 3], bar: [{a: 4, b: 5}, {a: 2, b: 3}]},
              {foo: [6, 7, 8], bar: [{a: 9, b: 1}, {a: 7, b: 8}]}]
    return self.z[0].foo[0] + self.z[0].foo[1] * 10 + self.z[0].foo[2] * 100 + \
        self.z[0].bar[0].a * 1000 + self.z[0].bar[0].b * 10000 + self.z[0].bar[1].a * 100000 + self.z[0].bar[1].b * 1000000 + \
        self.z[1].foo[0] * 10000000 + self.z[1].foo[1] * 100000000 + self.z[1].foo[2] * 1000000000 + \
        self.z[1].bar[0].a * 10000000000 + self.z[1].bar[0].b * 100000000000 + \
        self.z[1].bar[1].a * 1000000000000 + self.z[1].bar[1].b * 10000000000000

@public
def goo() -> num:
    goo: {foo: num, bar: num}[3]
    goo[0] = {foo: 1, bar: 2}
    goo[1] = {foo: 3, bar: 4}
    goo[2] = {foo: 5, bar: 6}
    return goo[0].foo + goo[0].bar * 10 + goo[1].foo * 100 + \
        goo[1].bar * 1000 + goo[2].foo * 10000 + goo[2].bar * 100000

@public
def gop() -> num:
    zed: {foo: num[3], bar: {a: num, b: num}[2]}[2] = [
        {foo: [1, 2, 3], bar: [{a: 4, b: 5}, {a: 2, b: 3}]},
        {foo: [6, 7, 8], bar: [{a: 9, b: 1}, {a: 7, b: 8}]}
    ]
    return zed[0].foo[0] + zed[0].foo[1] * 10 + zed[0].foo[2] * 100 + \
        zed[0].bar[0].a * 1000 + zed[0].bar[0].b * 10000 + zed[0].bar[1].a * 100000 + zed[0].bar[1].b * 1000000 + \
        zed[1].foo[0] * 10000000 + zed[1].foo[1] * 100000000 + zed[1].foo[2] * 1000000000 + \
        zed[1].bar[0].a * 10000000000 + zed[1].bar[0].b * 100000000000 + \
        zed[1].bar[1].a * 1000000000000 + zed[1].bar[1].b * 10000000000000
    """

    c = get_contract_with_gas_estimation(multi_setter_struct_test)
    assert c.foo() == 654321
    assert c.fop() == 87198763254321
    assert c.goo() == 654321
    assert c.gop() == 87198763254321

    print('Passed multi-setter struct test')


def test_type_converter_setter_test(get_contract_with_gas_estimation):
    type_converter_setter_test = """
mom: {a: {c: num}[3], b: num}
non: {a: {c: decimal}[3], b:num}
pap: decimal[2][2]

@public
def foo() -> num:
    self.mom = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    self.non = self.mom
    return floor(self.non.a[0].c + self.non.a[1].c * 10 + self.non.a[2].c * 100 + self.non.b * 1000)

@public
def goo() -> num:
    self.pap = [[1, 2], [3, 4]]
    return floor(self.pap[0][0] + self.pap[0][1] * 10 + self.pap[1][0] * 100 + self.pap[1][1] * 1000)
    """

    c = get_contract_with_gas_estimation(type_converter_setter_test)
    assert c.foo() == 4321
    assert c.foo() == 4321
    print('Passed type-conversion struct test')


def test_composite_setter_test(get_contract_with_gas_estimation):
    composite_setter_test = """
mom: {a: {c: num}[3], b:num}
qoq: {c: num}

@public
def foo() -> num:
    self.mom = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    non: {c: num}  = {c: 5}
    self.mom.a[0] = non
    non = {c: 6}
    self.mom.a[2] = non
    return self.mom.a[0].c + self.mom.a[1].c * 10 + self.mom.a[2].c * 100 + self.mom.b * 1000

@public
def fop() -> num:
    popp: {a: {c: num}[3], b:num} = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    self.qoq = {c: 5}
    popp.a[0] = self.qoq
    self.qoq = {c: 6}
    popp.a[2] = self.qoq
    return popp.a[0].c + popp.a[1].c * 10 + popp.a[2].c * 100 + popp.b * 1000

@public
def foq() -> num:
    popp: {a: {c: num}[3], b:num} = {a: [{c: 1}, {c: 2}, {c: 3}], b: 4}
    popp.a[0] = None
    popp.a[2] = None
    return popp.a[0].c + popp.a[1].c * 10 + popp.a[2].c * 100 + popp.b * 1000
    """

    c = get_contract_with_gas_estimation(composite_setter_test)
    assert c.foo() == 4625
    assert c.fop() == 4625
    assert c.foq() == 4020
    print('Passed composite struct test')
