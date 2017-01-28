from viper import parser, compile_lll, compiler_plugin
from viper.parser import InvalidTypeException, TypeMismatchException, VariableDeclarationException, StructureException, ConstancyViolationException
c = compiler_plugin.Compiler() 

def must_fail(code, exception_type):
    success = False
    try:
        c.compile(code)
    except exception_type as e:
        print(e)
        success = True
    assert success

def must_succeed(code):
    c.compile(code)
    print('Compilation successful')

must_fail("""
x: bat
""", InvalidTypeException)

must_fail("""
x: 5
""", InvalidTypeException)

must_fail("""
x: num[int]
""", InvalidTypeException)

must_fail("""
x: num[-1]
""", InvalidTypeException)

must_fail("""
x: num[3.5]
""", InvalidTypeException)

must_succeed("""
x: num[3]
""")

must_succeed("""
x: num[1][2][3][4][5]
""")

must_fail("""
x: {num[5]: num[7]}
""", InvalidTypeException)

must_fail("""
x: [bar, baz]
""", InvalidTypeException)

must_fail("""
x: [bar(num), baz(baffle)]
""", InvalidTypeException)

must_succeed("""
x: {bar: num, baz: num}
""")

must_fail("""
x: {bar: num, decimal: num}
""", InvalidTypeException)

must_fail("""
x: {bar: num, 5: num}
""", InvalidTypeException)

must_fail("""
x[5] = 4
""", StructureException)

must_fail("""
def foo(x): pass
""", InvalidTypeException)

must_succeed("""
def foo(x: num): pass
""")

must_fail("""
x: num
x: num
""", VariableDeclarationException)

must_fail("""
x: num

def foo(x: num): pass
""", VariableDeclarationException)

must_fail("""
def foo(x: num, x: num): pass
""", VariableDeclarationException)

must_fail("""
def foo(x: num):
    x = 5
""", VariableDeclarationException)

must_fail("""
def foo():
    x = 5
    x: num
""", VariableDeclarationException)

must_fail("""
def foo():
    x: num
    x: num
""", VariableDeclarationException)

must_succeed("""
def foo():
    x: num
    x = 5
""")

must_succeed("""
def foo():
    x = 5
""")

must_fail("""
def foo():
    num = 5
""", VariableDeclarationException)

must_fail("""
def foo():
    bork = zork
""", VariableDeclarationException)

must_fail("""
x: num
def foo():
    x = 5
""", VariableDeclarationException)

must_fail("""
def foo():
    x = 5
    x = '0x1234567890123456789012345678901234567890'
""", TypeMismatchException)

must_fail("""
def foo():
    x = 5
    x = 3.5
""", TypeMismatchException)

must_succeed("""
def foo():
    x = 5
    x = 3
""")

must_fail("""
b: num
def foo():
    b = 7
""", VariableDeclarationException)

must_succeed("""
b: num
def foo():
    self.b = 7
""")

must_fail("""
b: num
def foo():
    self.b = 7.5
""", TypeMismatchException)

must_succeed("""
b: decimal
def foo():
    self.b = 7.5
""")

must_succeed("""
b: decimal
def foo():
    self.b = 7
""")

must_fail("""
b: num[5]
def foo():
    self.b = 7
""", TypeMismatchException)

must_succeed("""
b: decimal[5]
def foo():
    self.b[0] = 7
""")

must_fail("""
b: num[5]
def foo():
    self.b[0] = 7.5
""", TypeMismatchException)

must_succeed("""
b: num[5]
def foo():
    a: num[5]
    self.b[0] = a[0]
""")

must_fail("""
b: num[5]
def foo():
    x = self.b[0][1]
""", TypeMismatchException)

must_fail("""
b: num[5]
def foo():
    x = self.b[0].cow
""", TypeMismatchException)

must_fail("""
b: {foo: num, bar: num}
def foo():
    x = self.b.cow
""", TypeMismatchException)

must_fail("""
b: {foo: num, bar: num}
def foo():
    x = self.b[0]
""", TypeMismatchException)

must_succeed("""
b: {foo: num, bar: num}
def foo():
    x = self.b.bar
""")

must_succeed("""
b: num[num]
def foo():
    x = self.b[5]
""")

must_fail("""
b: num[num]
def foo():
    x = self.b[5.7]
""", TypeMismatchException)

must_succeed("""
b: num[decimal]
def foo():
    x = self.b[5]
""")

must_fail("""
b: {num: num, address: address}
""", InvalidTypeException)

must_fail("""
b: num[num, decimal]
""", InvalidTypeException)

must_fail("""
b: num[num: address]
""", InvalidTypeException)

must_fail("""
b: num[num]
def foo():
    self.b[3] = 5.6
""", TypeMismatchException)

must_succeed("""
b: num[num]
def foo():
    self.b[3] = -5
""")

must_succeed("""
b: num[num]
def foo():
    self.b[-3] = 5
""")

must_fail("""
def foo():
    send(1, 2)
""", TypeMismatchException)

must_fail("""
def foo():
    send(1, 2)
""", TypeMismatchException)

must_fail("""
def foo():
    send("0x1234567890123456789012345678901234567890", 2.5)
""", TypeMismatchException)

must_fail("""
def foo():
    send("0x1234567890123456789012345678901234567890", "0x1234567890123456789012345678901234567890")
""", TypeMismatchException)

must_succeed("""
x: num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x)
""")

must_fail("""
x: num

def foo():
    send("0x1234567890123456789012345678901234567890", x)
""", VariableDeclarationException)

must_succeed("""
x: num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x + 1)
""")

must_fail("""
x: num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x + 1.5)
""", TypeMismatchException)

must_fail("""
x: decimal

def foo():
    send("0x1234567890123456789012345678901234567890", self.x)
""", TypeMismatchException)

must_succeed("""
x: decimal

def foo():
    send("0x1234567890123456789012345678901234567890", floor(self.x))
""")

must_succeed("""
def foo():
    selfdestruct("0x1234567890123456789012345678901234567890")
""")

must_fail("""
def foo():
    selfdestruct(7)
""", TypeMismatchException)

must_fail("""
def foo(): pass

x: num
""", StructureException)

must_fail("""
send("0x1234567890123456789012345678901234567890", 5)
""", StructureException)

must_fail("""
send("0x1234567890123456789012345678901234567890", 5)
""", StructureException)

must_fail("""
x: num[5]
def foo():
    self.x[2:4] = 3
""", StructureException)

must_fail("""
x: num[5]
def foo():
    z = self.x[2:4]
""", StructureException)

must_fail("""
def foo():
    x: num[5]
    z = x[2:4]
""", StructureException)

must_succeed("""
def foo():
    x: num[5]
    z = x[2]
""")

must_succeed("""
def foo():
    for i in range(10):
        pass
""")

must_fail("""
def foo():
    x = 5
    for i in range(x):
        pass
""", StructureException)

must_succeed("""
def foo():
    for i in range(10, 20):
        pass
""")

must_succeed("""
def foo():
    x = 5
    for i in range(x, x + 10):
        pass
""")

must_fail("""
def foo():
    x = 5
    y = 7
    for i in range(x, x + y):
        pass
""", StructureException)

must_fail("""
x: num
def foo() -> num(const):
    self.x = 5
""", ConstancyViolationException)

must_succeed("""
x: num
def foo() -> num:
    self.x = 5
""")

must_fail("""
def foo() -> num(const):
    send("0x1234567890123456789012345678901234567890", 5)
""", ConstancyViolationException)

must_fail("""
def foo() -> num(const):
    selfdestruct("0x1234567890123456789012345678901234567890")
""", ConstancyViolationException)

must_succeed("""
def foo():
    x = true
    z = x and false
""")

must_succeed("""
def foo():
    x = true
    z = x and False
""")

must_fail("""
def foo():
    x = true
    x = 5
""", TypeMismatchException)

must_fail("""
def foo():
    true = 3
""", VariableDeclarationException)

must_fail("""
def foo():
    True = 3
""", SyntaxError)

must_fail("""
foo: num[3]
def foo():
    self.foo = 5
""", TypeMismatchException)

must_succeed("""
foo: num[3]
def foo():
    self.foo[0] = 5
""")

must_succeed("""
foo: num[3]
def foo():
    self.foo = [1, 2, 3]
""")

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, 2, 3, 4]
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, 2]
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = {0: 5, 1: 7, 2: 9}
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = {a: 5, b: 7, c: 9}
""", TypeMismatchException)

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, 2, "0x1234567890123456789012345678901234567890"]
""", TypeMismatchException)

must_succeed("""
foo: decimal[3]
def foo():
    self.foo = [1, 2.1, 3]
""")

must_fail("""
foo: num[3]
def foo():
    self.foo = []
""", (TypeMismatchException, StructureException))

must_fail("""
foo: num[3]
def foo():
    self.foo = [1, [2], 3]
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = 5
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [2, 5]
""", TypeMismatchException)

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2], [3, 4, 5], [6, 7, 8]]
""", TypeMismatchException)

must_succeed("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
""")

must_fail("""
bar: num[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
""", TypeMismatchException)

must_succeed("""
bar: decimal[3][3]
def foo():
    self.bar = [[1, 2, 3], [4, 5, 6], [7, 8, 9.0]]
""")

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[2], b: num}
def foo():
    self.nom = self.mom
""", TypeMismatchException)

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: decimal}[2], b: num}
def foo():
    self.nom = self.mom
""", TypeMismatchException)

must_succeed("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: decimal}[3], b: num}
def foo():
    self.nom = self.mom
""")

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[3], b: num, c: num}
def foo():
    self.nom = self.mom
""", TypeMismatchException)

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[3]}
def foo():
    self.nom = self.mom
""", TypeMismatchException)

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}, b: num}
def foo():
    self.nom = self.mom
""", TypeMismatchException)

must_succeed("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.nom = self.mom.a
""")

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.nom = self.mom.b
""", TypeMismatchException)

must_succeed("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
""")

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5.5}
""", TypeMismatchException)

must_succeed("""
mom: {a: {c: decimal}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
""")

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {c: decimal}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
""", TypeMismatchException)

must_fail("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: self.nom}
""", TypeMismatchException)

must_succeed("""
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: null, b: 5}
""")

must_succeed("""
mom: {a: {c: num}[3], b: num}
def foo():
    nom: {c: num}[3]
    self.mom = {a: nom, b: 5}
""")

must_succeed("""
nom: {c: num}[3]
def foo():
    mom: {a: {c: num}[3], b: num}
    mom.a = self.nom
""")

must_fail("""
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom = None
""", TypeMismatchException)

must_fail("""
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom = {a: [{c: 5}], b: 7}
""", TypeMismatchException)

must_succeed("""
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom.a[135] = {c: 6}
    self.nom.b = 9
""")

must_succeed("""
def foo(x: timestamp) -> timestamp:
    return x
""")

must_succeed("""
def foo(x: timestamp) -> num(const):
    return 5
""")

must_succeed("""
def foo(x: timestamp) -> timestamp(const):
    return x
""")

must_succeed("""
def foo(x: timestamp) -> timestamp:
    y = x
    return y
""")

must_fail("""
def foo(x: timestamp) -> num:
    return x
""", TypeMismatchException)

must_fail("""
def foo(x: timestamp) -> timedelta:
    return x
""", TypeMismatchException)

must_succeed("""
def foo(x: timestamp, y: timestamp) -> bool:
    return y > x
""")

must_succeed("""
def foo(x: timedelta, y: timedelta) -> bool:
    return y == x
""")

must_fail("""
def foo(x: timestamp, y: timedelta) -> bool:
    return y < x
""", TypeMismatchException)

must_succeed("""
def foo(x: timestamp) -> timestamp:
    return x + 50
""")

must_succeed("""
def foo() -> timestamp:
    return 720
""")

must_succeed("""
def foo() -> timedelta:
    return 720
""")

must_succeed("""
def foo(x: timestamp, y: timedelta) -> timestamp:
    return x + y
""")

must_fail("""
def foo(x: timestamp, y: timedelta) -> timedelta:
    return x + y
""", TypeMismatchException)

must_fail("""
def foo(x: timestamp, y: timestamp) -> timestamp:
    return x + y
""", TypeMismatchException)

must_succeed("""
def foo(x: timestamp, y: timestamp) -> timedelta:
    return x - y
""")

must_succeed("""
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x + y
""")

must_succeed("""
def foo(x: timedelta) -> timedelta:
    return x * 2
""")

must_fail("""
def foo(x: timestamp) -> timestamp:
    return x * 2
""", TypeMismatchException)

must_fail("""
def foo(x: timedelta, y: timedelta) -> timedelta:
    return x * y
""", TypeMismatchException)

must_succeed("""
def foo(x: timedelta) -> bool:
    return x > 50
""")

must_succeed("""
def foo(x: timestamp) -> bool:
    return x > 12894712
""")

must_succeed("""
def foo() -> timestamp:
    x: timestamp
    x = 30
    return x
""")

must_fail("""
def foo() -> timestamp:
    x = 30
    y: timestamp
    return x + y
""", TypeMismatchException)

must_succeed("""
a: timestamp[timestamp]

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
""")

must_fail("""
a: num[timestamp]

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
""", TypeMismatchException)

must_fail("""
a: timestamp[num]

def add_record():
    self.a[block.timestamp] = block.timestamp + 20
""", TypeMismatchException)

must_fail("""
def add_record():
    a = {x: block.timestamp}
    b = {y: 5}
    a.x = b.y
""", TypeMismatchException)

must_succeed("""
def add_record():
    a = {x: block.timestamp}
    a.x = 5
""")

must_succeed("""
def foo() -> num:
    return as_number(block.timestamp)
""")

must_fail("""
def foo() -> address:
    return as_number(block.coinbase)
""", TypeMismatchException)

must_fail("""
def foo() -> address:
    return as_number([1, 2, 3])
""", TypeMismatchException)

must_succeed("""
def foo(x: timedelta, y: num (wei/sec)) -> wei_value:
    return x * y
""")

must_fail("""
def foo(x: timedelta, y: num (wei/sec)) -> num:
    return x * y
""", TypeMismatchException)

must_fail("""
def foo(x: timestamp, y: num (wei/sec)) -> wei_value:
    return x * y
""", TypeMismatchException)

must_succeed("""
def foo(x: wei_value, y: currency_value, z: num (wei*currency/sec**2)) -> num (sec**2):
    return x * y / z
""")

must_succeed("""
x: timedelta
def foo() -> num(sec):
    return self.x
""")

must_succeed("""
x: timedelta
y: num
def foo() -> num(sec, const):
    return self.x
""")

must_fail("""
x: timedelta
y: num
def foo() -> num(sec, const):
    self.y = 9
    return 5
""", ConstancyViolationException)

must_succeed("""
x: timedelta
y: num
def foo() -> num(sec):
    self.y = 9
    return 5
""")
