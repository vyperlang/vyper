from viper import compiler
from viper.exceptions import InvalidTypeException, \
    TypeMismatchException, \
    VariableDeclarationException, \
    StructureException, \
    ConstancyViolationException, \
    InvalidLiteralException, \
    NonPayableViolationException

# These functions register test cases
# for pytest functions at the end
fail_list = []


def must_fail(code, exception):
    fail_list.append((code, exception))

pass_list = []


def must_succeed(code):
    pass_list.append(code)

# TEST CASES
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
def foo(num: num):
    pass
""", VariableDeclarationException)

must_fail("""
def foo(x: num):
    x = 5
""", ConstancyViolationException)

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

must_fail("""
def foo():
    x: num
def foo():
    y: num
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
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_fail("""
def foo():
    x = 0x12345678901234567890123456789012345678901
""", InvalidLiteralException)

must_fail("""
def foo():
    x = 0x01234567890123456789012345678901234567890
""", InvalidLiteralException)

must_fail("""
def foo():
    x = 0x123456789012345678901234567890123456789
""", InvalidLiteralException)

must_fail("""
def foo():
    x = -170141183460469231731687303715884105728
""", InvalidLiteralException)

must_fail("""
def foo():
    x = -170141183460469231731687303715884105728.
""", InvalidLiteralException)

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

must_fail("""
b: decimal
def foo():
    self.b = 7.5178246872145875217495129745982164981654986129846
""", InvalidLiteralException)

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
b: {foo: num}
def foo():
    self.b = {foo: 1, foo: 2}
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

must_succeed("""
def foo() -> bool:
    return 1 == 1
""")

must_succeed("""
def foo() -> bool:
    return 1 != 1
""")

must_succeed("""
def foo() -> bool:
    return 1 > 1
""")

must_succeed("""
def foo() -> bool:
    return 1. >= 1
""")

must_succeed("""
def foo() -> bool:
    return 1 < 1
""")

must_succeed("""
def foo() -> bool:
    return 1 <= 1.
""")

must_fail("""
def foo() -> bool:
    return (1 == 2) <= (1 == 1)
""", TypeMismatchException)

must_fail("""
def foo() -> bool:
    return (1 == 2) or 3
""", TypeMismatchException)

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
    send(0x1234567890123456789012345678901234567890, 2.5)
""", TypeMismatchException)

must_fail("""
def foo():
    send(0x1234567890123456789012345678901234567890, 0x1234567890123456789012345678901234567890)
""", TypeMismatchException)

must_succeed("""
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
""")

must_fail("""
x: num

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
""", TypeMismatchException)

must_fail("""
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, x)
""", VariableDeclarationException)

must_succeed("""
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1)
""")

must_fail("""
x: wei_value

def foo():
    send(0x1234567890123456789012345678901234567890, self.x + 1.5)
""", TypeMismatchException)

must_fail("""
x: decimal

def foo():
    send(0x1234567890123456789012345678901234567890, self.x)
""", TypeMismatchException)

must_succeed("""
x: decimal

def foo():
    send(0x1234567890123456789012345678901234567890, as_wei_value(floor(self.x), wei))
""")

must_succeed("""
def foo():
    selfdestruct(0x1234567890123456789012345678901234567890)
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
send(0x1234567890123456789012345678901234567890, 5)
""", StructureException)

must_fail("""
send(0x1234567890123456789012345678901234567890, 5)
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
@constant
def foo() -> num:
    self.x = 5
""", ConstancyViolationException)

must_fail("""
x: num
@const
def foo() -> num:
    pass
""", StructureException)

must_fail("""
x: num
@monkeydoodledoo
def foo() -> num:
    pass
""", StructureException)

must_fail("""
x: num
@constant(123)
def foo() -> num:
    pass
""", StructureException)

must_succeed("""
x: num
def foo() -> num:
    self.x = 5
""")

must_succeed("""
x: num
@payable
def foo() -> num:
    self.x = 5
""")

must_succeed("""
x: num
@internal
def foo() -> num:
    self.x = 5
""")

must_fail("""
@constant
def foo() -> num:
    send(0x1234567890123456789012345678901234567890, 5)
""", ConstancyViolationException)

must_fail("""
@constant
def foo() -> num:
    selfdestruct(0x1234567890123456789012345678901234567890)
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
    self.foo = [1, 2, 0x1234567890123456789012345678901234567890]
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
@constant
def foo(x: timestamp) -> num:
    return 5
""")

must_succeed("""
@constant
def foo(x: timestamp) -> timestamp:
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
    return as_unitless_number(block.timestamp)
""")

must_fail("""
def foo() -> address:
    return as_unitless_number(block.coinbase)
""", TypeMismatchException)

must_fail("""
def foo() -> address:
    return as_unitless_number([1, 2, 3])
""", TypeMismatchException)

must_succeed("""
def foo(x: timedelta, y: num (wei/sec)) -> wei_value:
    return x * y
""")

must_succeed("""
def foo(x: num(sec, positional)) -> timestamp:
    return x
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
@constant
def foo() -> num(sec):
    return self.x
""")

must_fail("""
x: timedelta
y: num
@constant
def foo() -> num(sec):
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

must_succeed("""
def foo(x: bytes <= 100) -> bytes <= 100:
    return x
""")

must_succeed("""
def foo(x: bytes <= 100) -> bytes <= 150:
    return x
""")

must_fail("""
def foo(x: bytes <= 100) -> bytes <= 75:
    return x
""", TypeMismatchException)

must_fail("""
def foo(x: bytes <= 100) -> num:
    return x
""", TypeMismatchException)

must_fail("""
def foo(x: num) -> bytes <= 75:
    return x
""", TypeMismatchException)

must_succeed("""
def baa():
    x: bytes <= 50
""")

must_fail("""
def baa() -> decimal:
    return 2.0**2
""", TypeMismatchException)

must_fail("""
def baa():
    x: bytes <= 50
    y: bytes <= 50
    z = x + y
""", TypeMismatchException)

must_fail("""
def baa():
    x: bytes <= 50
    y: num
    y = x
""", TypeMismatchException)

must_fail("""
def baa():
    x: bytes <= 50
    y: num
    x = y
""", TypeMismatchException)

must_fail("""
def baa():
    x: bytes <= 50
    y: bytes <= 60
    x = y
""", TypeMismatchException)

must_succeed("""
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=2, len=3)
""")

must_succeed("""
def foo(inp: bytes <= 10) -> bytes <= 4:
    return slice(inp, start=2, len=3)
""")

must_fail("""
def foo(inp: bytes <= 10) -> bytes <= 2:
    return slice(inp, start=2, len=3)
""", TypeMismatchException)

must_fail("""
def foo(inp: num) -> bytes <= 3:
    return slice(inp, start=2, len=3)
""", TypeMismatchException)

must_fail("""
def foo() -> num:
    return block.fail
""", Exception)

must_fail("""
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=block.timestamp, len=3)
""", TypeMismatchException)

must_fail("""
def foo(inp: bytes <= 10) -> bytes <= 3:
    return slice(inp, start=4.0, len=3)
""", TypeMismatchException)

must_succeed("""
def foo(inp: bytes <= 10) -> num:
    return len(inp)
""")

must_fail("""
def foo(inp: num) -> num:
    return len(inp)
""", TypeMismatchException)

must_succeed("""
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i2)
""")

must_succeed("""
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i1, i1, i1)
""")

must_succeed("""
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i1)
""")

must_fail("""
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, i2, i1, i1)
""", TypeMismatchException)

must_fail("""
def cat(i1: bytes <= 10, i2: bytes <= 30) -> bytes <= 40:
    return concat(i1, 5)
""", TypeMismatchException)

must_succeed("""
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 25:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
""")

must_fail("""
y: bytes <= 10

def krazykonkat(z: bytes <= 10) -> bytes <= 24:
    x = "cow"
    self.y = "horse"
    return concat(x, " ", self.y, " ", z)
""", TypeMismatchException)

must_succeed("""
def foo() -> bytes <= 10:
    return "badminton"
""")

must_fail("""
def foo() -> bytes <= 10:
    return "badmintonzz"
""", TypeMismatchException)

must_succeed("""
def foo() -> bytes <= 10:
    return slice("badmintonzzz", start=1, len=10)
""")

must_fail("""
def foo() -> bytes <= 10:
    x = '0x1234567890123456789012345678901234567890'
    x = 0x1234567890123456789012345678901234567890
""", TypeMismatchException)

must_fail("""
def foo():
    x = "these bytes are nо gооd because the o's are from the Russian alphabet"
""", InvalidLiteralException)

must_fail("""
def foo():
    x = "这个傻老外不懂中文"
""", InvalidLiteralException)

must_succeed("""
def foo():
    x = "¡très bien!"
""")

must_succeed("""
def foo():
    x = sha3("moose")
""")

must_succeed("""
def foo():
    x = sha3(0x1234567890123456789012345678901234567890123456789012345678901234)
""")

must_fail("""
def foo():
    x = sha3("moose", 3)
""", StructureException)

must_fail("""
def foo():
    x = sha3(3)
""", TypeMismatchException)

must_fail("""
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 163:
    return concat(inp2, inp, inp2)
""", TypeMismatchException)

must_succeed("""
def sandwich(inp: bytes <= 100, inp2: bytes32) -> bytes <= 165:
    return concat(inp2, inp, inp2)
""")

must_succeed("""
def convert1(inp: bytes32) -> num256:
    return as_num256(inp)
""")

must_succeed("""
def convert2(inp: num256) -> bytes32:
    return as_bytes32(inp)
""")

must_fail("""
def convert2(inp: num256) -> address:
    return as_bytes32(inp)
""", TypeMismatchException)

must_succeed("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757)
""")

must_succeed("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757, value=as_wei_value(9, wei))
""")

must_succeed("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757, value=9)
""")

must_fail("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow")
""", StructureException)

must_fail("""
def foo():
    x = raw_call(0x123456789012345678901234567890123456789, "cow", outsize=4)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, outsize=9)
""", SyntaxError)

must_fail("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, outsize=4)
""", StructureException)

must_fail("""
@constant
def foo() -> num:
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", outsize=4, gas=595757, value=9)
    return 5
""", ConstancyViolationException)

must_succeed("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890)
""")

must_succeed("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=as_wei_value(9, wei))
""")

must_succeed("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=9)
""")

must_fail("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, "cow")
""", StructureException)

must_fail("""
def foo():
    x = create_with_code_of(0x123456789012345678901234567890123456789)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=4, value=9)
""", SyntaxError)

must_fail("""
def foo():
    x = raw_call(0x1234567890123456789012345678901234567890, "cow", gas=111111, outsize=4, moose=9)
""", StructureException)

must_fail("""
def foo():
    x = create_with_code_of(0x1234567890123456789012345678901234567890, outsize=4)
""", StructureException)

must_fail("""
@constant
def foo() -> num:
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=9)
    return 5
""", ConstancyViolationException)

must_fail("""
def foo() -> num:
    x = create_with_code_of(0x1234567890123456789012345678901234567890, value=block.timestamp)
    return 5
""", TypeMismatchException)

must_fail("""
def foo() -> num256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0)
""", TypeMismatchException)

must_succeed("""
def foo() -> num256:
    return extract32("cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc", 0, type=num256)
""")

must_succeed("""
x: bytes <= 100
def foo() -> num256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 0, type=num256)
""")

must_succeed("""
x: bytes <= 100
def foo() -> num256:
    self.x = "cowcowcowcowcowccowcowcowcowcowccowcowcowcowcowccowcowcowcowcowc"
    return extract32(self.x, 1, type=num256)
""")

must_succeed("""
def foo():
    x = as_wei_value(5, finney) + as_wei_value(2, babbage) + as_wei_value(8, shannon)
""")

must_succeed("""
def foo():
    z = 2 + 3
    x = as_wei_value(2 + 3, finney)
""")

must_succeed("""
def foo():
    x = as_wei_value(5.182, ada)
""")

must_fail("""
def foo():
    x = as_wei_value(5.1824, ada)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = as_wei_value(0x05, ada)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = as_wei_value(5, vader)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = as_wei_value(5, 'szabo')
""", TypeMismatchException)

must_succeed("""
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[0]
""")

must_succeed("""
def foo() -> bytes32:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
""")

must_fail("""
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[1]
""", TypeMismatchException)

must_fail("""
def foo() -> address:
    x = RLPList('\xf6\x9455555555555555555555\xa0GGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG', [address, bytes32])
    return x[2]
""", TypeMismatchException)

must_succeed("""
def foo() -> bytes <= 500:
    x = RLPList('\xe0xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
""")

must_fail("""
def foo() -> bytes <= 500:
    x = RLPList('\xe1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx', [bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes, bytes])
    return x[1]
""", TypeMismatchException)

must_succeed("""
x: public(num)
""")

must_fail("""
x: public()
""", StructureException)

must_fail("""
def foo():
    raw_log([], 0x1234567890123456789012345678901234567890)
""", TypeMismatchException)

must_fail("""
def foo():
    raw_log([], "cow", "dog")
""", StructureException)

must_fail("""
def foo():
    raw_log("cow", "dog")
""", StructureException)

must_fail("""
def foo():
    raw_log(["cow"], "dog")
""", TypeMismatchException)

must_fail("""
def foo():
    send(0xde0b295669a9fd93d5f28d9ec85e40f4cb697bae, 5)
""", InvalidLiteralException)

must_succeed("""
def foo():
    send(0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe, 5)
""")

must_succeed("""
def foo():
    throw
""")

must_fail("""
def foo():
    throe
""", StructureException)

must_succeed("""
def foo(x: num[3]) -> num:
    return x[0]
""")

must_succeed("""
y: num[3]

def foo(x: num[3]) -> num:
    self.y = x
""")

must_fail("""
y: num[3]

def foo(x: num[3]) -> num:
    self.y = x[0]
""", TypeMismatchException)

must_fail("""
y: num[3]

def foo(x: num[3]) -> num:
    self.y[0] = x
""", TypeMismatchException)

must_fail("""
y: num[4]

def foo(x: num[3]) -> num:
    self.y = x
""", TypeMismatchException)

must_succeed("""
y: decimal[3]

def foo(x: num[3]) -> num:
    self.y = x
""")

must_succeed("""
y: decimal[2][2]

def foo(x: num[2][2]) -> num:
    self.y = x
""")

must_fail("""
y: address[2][2]

def foo(x: num[2][2]) -> num:
    self.y = x
""", TypeMismatchException)

must_succeed("""
y: decimal[2]

def foo(x: num[2][2]) -> num:
    self.y = x[1]
""")

must_succeed("""
def foo() -> num[2]:
    return [3,5]
""")

must_fail("""
def foo() -> num[2]:
    return [3,5,7]
""", TypeMismatchException)

must_fail("""
def foo() -> num[2]:
    return [3]
""", TypeMismatchException)

must_fail("""
def foo() -> num[2]:
    return [[1,2],[3,4]]
""", TypeMismatchException)

must_fail("""
def foo() -> num[2][2]:
    return [1,2]
""", TypeMismatchException)

must_succeed("""
def foo() -> num[2][2]:
    return [[1,2],[3,4]]
""")

must_succeed("""
def foo() -> decimal[2][2]:
    return [[1,2],[3,4]]
""")

must_succeed("""
def foo() -> decimal[2][2]:
    return [[1,2.0],[3.5,4]]
""")

must_fail("""
def foo() -> num[2]:
    return [3,block.timestamp]
""", TypeMismatchException)

must_fail("""
def foo() -> timedelta[2]:
    return [block.timestamp - block.timestamp, block.timestamp]
""", TypeMismatchException)

must_succeed("""
def foo() -> timestamp[2]:
    return [block.timestamp + 86400, block.timestamp]
""")

must_succeed("""
def foo():
    pass

def goo():
    self.foo()
""")

must_fail("""
def foo():
    self.goo()

def goo():
    self.foo()
""", VariableDeclarationException)

must_succeed("""
@payable
def foo():
    x = msg.value
""")

must_fail("""
def foo():
    x = msg.value
""", NonPayableViolationException)

must_succeed("""
def foo() -> num(wei):
    x = 0x1234567890123456789012345678901234567890
    return x.balance
""")

must_fail("""
def foo() -> num(wei):
    x = 0x1234567890123456789012345678901234567890
    return x.balance()
""", StructureException)

must_fail("""
def foo() -> num(wei):
    x = 45
    return x.balance
""", TypeMismatchException)

must_succeed("""
def foo() -> num:
    x = 0x1234567890123456789012345678901234567890
    return x.codesize
""")

must_fail("""
def foo() -> num:
    x = 0x1234567890123456789012345678901234567890
    return x.codesize()
""", StructureException)

must_fail("""
def foo() -> num:
    x = 45
    return x.codesize
""", TypeMismatchException)

must_fail("""
def foo() -> num(wei):
    x = 0x1234567890123456789012345678901234567890
    return x.codesize
""", TypeMismatchException)

must_succeed("""
def foo() -> num(wei / sec):
    x = as_wei_value(5, finney)
    y = block.timestamp + 50 - block.timestamp
    return x / y
""")

must_succeed("""
x: public(num(wei / sec))
y: public(num(wei / sec ** 2))
z: public(num(1 / sec))

def foo() -> num(sec ** 2):
    return self.x / self.y / self.z
""")

must_fail("""
def foo() -> num(wei / sec):
    x = as_wei_value(5, finney)
    y = block.timestamp + 50
    return x / y
""", TypeMismatchException)

must_fail("""
x: num[address[bool]]
def foo() -> num(wei / sec):
    pass
""", InvalidTypeException)

must_fail("""
x: {cow: num, cor: num}
def foo():
    self.x.cof = 1
""", TypeMismatchException)

must_fail("""
def foo():
    BALANCE = 45
""", VariableDeclarationException)

must_succeed("""
def foo():
    MOOSE = 45
""")

must_fail("""
def foo():
    x = -self
""", TypeMismatchException)

must_fail("""
def foo():
    x = ~self
""", StructureException)

must_fail("""
def foo() -> {cow: num, dog: num}:
    return {cow: 5, dog: 7}
""", InvalidTypeException)

must_fail("""
def foo() -> num:
    return {cow: 5, dog: 7}
""", TypeMismatchException)

must_succeed("""
def foo():
    x = True
    x = False
""")

must_fail("""
def foo():
    x = [1, 2, 3]
    x = 4
""", TypeMismatchException)

must_fail("""
def foo() -> num:
    return
""", TypeMismatchException)

must_fail("""
def foo():
    return 3
""", TypeMismatchException)

must_fail("""
def foo():
    x = as_num256(821649876217461872458712528745872158745214187264875632587324658732648753245328764872135671285218762145)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = slice("cow", start=0, len=block.timestamp)
""", TypeMismatchException)

must_fail("""
def foo():
    x = concat("")
""", StructureException)

must_fail("""
def foo():
    x = as_num256(-1)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = as_num256(3.1415)
""", InvalidLiteralException)

must_fail("""
def foo():
    x = [1, 2, 3]
    x = [4, 5, 6, 7]
""", TypeMismatchException)

must_succeed("""
def foo():
    x = [1, 2, 3]
    x = [4, 5, 6]
""")

must_fail("""
def foo():
    x = y = 3
""", StructureException)

must_succeed("""
def foo():
    x = block.difficulty + 185
    if tx.origin == self:
        y = concat(block.prevhash, "dog")
""")

must_fail("""
def foo():
    x = True
    x = 129
""", TypeMismatchException)

must_fail("""
def foo():
    y = min(7, as_num256(3))
""", TypeMismatchException)

must_fail("""
def foo():
    y = min(7, 0x1234567890123456789012345678901234567890)
""", TypeMismatchException)

must_fail("""
def foo():
    x = 7
    y = min(x, block.timestamp)
""", TypeMismatchException)

must_fail("""
def foo():
    y = min(block.timestamp + 30 - block.timestamp, block.timestamp)
""", TypeMismatchException)

must_succeed("""
def foo():
    y = min(block.timestamp + 30, block.timestamp + 50)
""")

# Run all of our registered tests
import pytest
from pytest import raises


@pytest.mark.parametrize('bad_code,exception_type', fail_list)
def test_compilation_fails_with_exception(bad_code, exception_type):
    with raises(exception_type):
        compiler.compile(bad_code)


@pytest.mark.parametrize('good_code', pass_list)
def test_compilation_succeeds(good_code):
    assert compiler.compile(good_code) is not None
