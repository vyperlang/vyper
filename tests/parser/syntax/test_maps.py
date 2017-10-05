import pytest
from pytest import raises

from viper import compiler
from viper.exceptions import TypeMismatchException


fail_list = [
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[2], b: num}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: decimal}[2], b: num}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[3], b: num, c: num}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}[3]}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: num}, b: num}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.nom = self.mom.b
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5.5}
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: decimal}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: self.nom}
    """,
    """
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom = None
    """,
    """
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom = {a: [{c: 5}], b: 7}
    """,
    """
foo: num[3]
def foo():
    self.foo = {0: 5, 1: 7, 2: 9}
    """,
    """
foo: num[3]
def foo():
    self.foo = {a: 5, b: 7, c: 9}
    """,
    """
def foo() -> num:
    return {cow: 5, dog: 7}
    """,
    """
x: {cow: num, cor: num}
def foo():
    self.x.cof = 1
    """,
    """
b: {foo: num}
def foo():
    self.b = {foo: 1, foo: 2}
    """,
    """
b: {foo: num, bar: num}
def foo():
    x = self.b.cow
    """,
    """
b: {foo: num, bar: num}
def foo():
    x = self.b[0]
    """
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
mom: {a: {c: num}[3], b: num}
nom: {a: {c: decimal}[3], b: num}
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.nom = self.mom.a
    """,
    """
nom: {a: {c: num}[num], b: num}
def foo():
    self.nom.a[135] = {c: 6}
    self.nom.b = 9
    """,
    """
nom: {c: num}[3]
def foo():
    mom: {a: {c: num}[3], b: num}
    mom.a = self.nom
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
mom: {a: {c: num}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: null, b: 5}
    """,
    """
mom: {a: {c: num}[3], b: num}
def foo():
    nom: {c: num}[3]
    self.mom = {a: nom, b: 5}
    """,
    """
mom: {a: {c: decimal}[3], b: num}
nom: {c: num}[3]
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
b: {foo: num, bar: num}
def foo():
    x = self.b.bar
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None
