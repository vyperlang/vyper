import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import (
    TypeMismatchException,
    VariableDeclarationException
)


fail_list = [
    """
struct A:
    x: int128
a: A
@public
def foo():
    self.a = A(1)
    """,
    """
struct A:
    x: int128
a: A
@public
def foo():
    self.a = A({x: 1, y: 2})
    """,
    """
struct A:
    x: int128
    y: int128
a: A
@public
def foo():
    self.a = A({x: 1})
    """,
    """
struct A:
    x: int128
struct B:
    x: int128
a: A
b: B
@public
def foo():
    self.a = A(self.b)
    """,
    """
struct A:
    x: int128
a: A
b: A
@public
def foo():
    self.a = A(self.b)
    """,
    """
struct A:
    x: int128
    y: int128
a: A
@public
def foo():
    self.a = A({x: 1})
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C[2]
    b: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C1:
    c: int128
struct C2:
    c: decimal
struct Mom:
    a: C1[3]
    b: int128
struct Nom:
    a: C2[2]
    b: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C[3]
    b: int128
    c: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C[3]
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C[3]
    b: int128
    c: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C
    b: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct Mom:
    a: int128
struct Nom:
    a: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = self.mom # require cast
    """,
    """
struct Mom:
    a: int128
struct Nom:
    b: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C[3]
    b: int128
mom: Mom
nom: Nom
@public
def foo():
    self.nom = self.mom # require cast
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C
mom: Mom
nom: C[3]
@public
def foo():
    self.nom = self.mom.b
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C
mom: Mom
nom: C[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: 5.5})
    """,
    """
struct C1:
    c: int128
struct C2:
    c: decimal
struct Mom:
    a: C1[3]
    b: int128
mom: Mom
nom: C2[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: 5})
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
struct Nom:
    a: C
mom: Mom
nom: C[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: self.nom})
    """,
    """
struct C:
    c: int128
struct Nom:
    a: map(int128, C)
    b: int128
nom: Nom
@public
def foo():
    clear(self.nom)
    """,
    """
struct C:
    c: int128
struct Nom:
    a: map(int128, C)
    b: int128
nom: Nom
@public
def foo():
    self.nom = Nom({a: [C({c: 5})], b: 7})
    """,
    """
struct C1:
    c: int128
struct C2:
    c: decimal
struct Mom:
    a: C1[3]
    b: int128
struct Nom:
    a: C2[3]
    b: int128
nom: Nom
mom: Mom
@public
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct C1:
    c: int128
struct C2:
    c: decimal
struct Mom:
    a: C1[3]
    b: int128
mom: Mom
nom: C2[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: 5})
    """,
    """
struct Bar:
    a: int128
    b: int128
    c: int128
bar: int128[3]
@public
def foo():
    self.bar = Bar({0: 5, 1: 7, 2: 9})
    """,
    """
struct Bar:
    a: int128
    b: int128
    c: int128
bar: int128[3]
@public
def foo():
    self.bar = Bar({a: 5, b: 7, c: 9})
    """,
    """
struct Farm:
    cow: int128
    dog: int128
@public
def foo() -> int128:
    f: Farm = Farm({cow: 5, dog: 7})
    return f
    """,
    """
struct X:
    cow: int128
    cor: int128
x: X
@public
def foo():
    self.x.cof = 1
    """,
    """
struct B:
    foo: int128
b: B
@public
def foo():
    self.b = B({foo: 1, foo: 2})
    """,
    """
struct B:
    foo: int128
    bar: int128
b: B
@public
def foo():
    x = self.b.cow
    """,
    """
struct B:
    foo: int128
    bar: int128
b: B
@public
def foo():
    x = self.b[0]
    """,
    ("""
struct X:
    bar: int128
    decimal: int128
    """, VariableDeclarationException),
    ("""
struct B:
    num: int128
    address: address
    """, VariableDeclarationException),
    ("""
struct B:
    num: int128
    address: address
    """, VariableDeclarationException)
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):
    if isinstance(bad_code, tuple):
        with raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with raises(TypeMismatchException):
            compiler.compile_code(bad_code)


valid_list = [
    """
struct A:
    x: int128
a: A
@public
def foo():
    self.a = A({x: 1})
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
nom: C[3]
@public
def foo():
    self.nom = self.mom.a
    """,
    """
struct C:
    c: int128
struct Nom:
    a: map(int128, C)
    b: int128
nom: Nom
@public
def foo():
    self.nom.a[135] = C({c: 6})
    self.nom.b = 9
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
nom: C[3]
@public
def foo():
    mom: Mom
    mom.a = self.nom
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
nom: C[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: 5})
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
nom: C[3]
@public
def foo():
    self.mom = Mom({a: self.nom, b: 5})
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
@public
def foo():
    nom: C[3]
    self.mom = Mom({a: nom, b: 5})
    """,
    """
struct B:
    foo: int128
    bar: int128
b: B
@public
def foo():
    x: int128 = self.b.bar
    """,
    """
struct X:
    bar: int128
    baz: int128
x: X
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None
