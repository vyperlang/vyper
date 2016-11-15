import parser, compile_lll
from parser import InvalidTypeException, TypeMismatchException, VariableDeclarationException, StructureException, ConstancyViolationException
import compiler_plugin
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
x = bat
""", InvalidTypeException)

must_fail("""
x = 5
""", InvalidTypeException)

must_fail("""
x = num[int]
""", InvalidTypeException)

must_fail("""
x = num[-1]
""", InvalidTypeException)

must_fail("""
x = num[3.5]
""", InvalidTypeException)

must_succeed("""
x = num[3]
""")

must_succeed("""
x = num[1][2][3][4][5]
""")

must_fail("""
x = {num[5]: num[7]}
""", InvalidTypeException)

must_fail("""
x = [bar, baz]
""", InvalidTypeException)

must_fail("""
x = [bar(num), baz(baffle)]
""", InvalidTypeException)

must_succeed("""
x = {bar: num, baz: num}
""")

must_fail("""
x = {bar: num, decimal: num}
""", InvalidTypeException)

must_fail("""
x = {bar: num, 5: num}
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
x = num
x = num
""", VariableDeclarationException)

must_fail("""
x = num

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
    x = num
""", VariableDeclarationException)

must_fail("""
def foo():
    x = num
    x = num
""", VariableDeclarationException)

must_succeed("""
def foo():
    x = num
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
x = num
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
b = num
def foo():
    b = 7
""", VariableDeclarationException)

must_succeed("""
b = num
def foo():
    self.b = 7
""")

must_fail("""
b = num
def foo():
    self.b = 7.5
""", TypeMismatchException)

must_succeed("""
b = decimal
def foo():
    self.b = 7.5
""")

must_succeed("""
b = decimal
def foo():
    self.b = 7
""")

must_fail("""
b = num[5]
def foo():
    self.b = 7
""", TypeMismatchException)

must_succeed("""
b = decimal[5]
def foo():
    self.b[0] = 7
""")

must_fail("""
b = num[5]
def foo():
    self.b[0] = 7.5
""", TypeMismatchException)

must_fail("""
b = num[5]
def foo():
    a = num[5]
    self.b = a
""", TypeMismatchException)

must_succeed("""
b = num[5]
def foo():
    a = num[5]
    self.b[0] = a[0]
""")

must_fail("""
b = num[5]
def foo():
    x = self.b[0][1]
""", TypeMismatchException)

must_fail("""
b = num[5]
def foo():
    x = self.b[0].cow
""", TypeMismatchException)

must_fail("""
b = {foo: num, bar: num}
def foo():
    x = self.b.cow
""", TypeMismatchException)

# TODO
must_fail("""
b = {foo: num, bar: num}
def foo():
    x = self.b[0]
""", TypeMismatchException)

must_succeed("""
b = {foo: num, bar: num}
def foo():
    x = self.b.bar
""")

must_succeed("""
b = num[num]
def foo():
    x = self.b[5]
""")

must_fail("""
b = num[num]
def foo():
    x = self.b[5.7]
""", TypeMismatchException)

must_succeed("""
b = num[decimal]
def foo():
    x = self.b[5]
""")

must_fail("""
b = {num: num, address: address}
""", InvalidTypeException)

must_fail("""
b = num[num, decimal]
""", InvalidTypeException)

must_fail("""
b = num[num: address]
""", InvalidTypeException)

must_fail("""
b = num[num]
def foo():
    self.b[3] = 5.6
""", TypeMismatchException)

must_succeed("""
b = num[num]
def foo():
    self.b[3] = -5
""")

must_succeed("""
b = num[num]
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
x = num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x)
""")

must_fail("""
x = num

def foo():
    send("0x1234567890123456789012345678901234567890", x)
""", VariableDeclarationException)

must_succeed("""
x = num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x + 1)
""")

must_fail("""
x = num

def foo():
    send("0x1234567890123456789012345678901234567890", self.x + 1.5)
""", TypeMismatchException)

must_fail("""
x = decimal

def foo():
    send("0x1234567890123456789012345678901234567890", self.x)
""", TypeMismatchException)

must_succeed("""
x = decimal

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

x = num
""", StructureException)

must_fail("""
send("0x1234567890123456789012345678901234567890", 5)
""", StructureException)

must_fail("""
send("0x1234567890123456789012345678901234567890", 5)
""", StructureException)

must_fail("""
x = num[5]
def foo():
    self.x[2:4] = 3
""", StructureException)

must_fail("""
x = num[5]
def foo():
    z = self.x[2:4]
""", StructureException)

must_fail("""
def foo():
    x = num[5]
    z = x[2:4]
""", StructureException)

must_succeed("""
def foo():
    x = num[5]
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
x = num
def foo() -> num(const):
    self.x = 5
""", ConstancyViolationException)

must_succeed("""
x = num
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
