import pytest
from pytest import raises

from vyper import compiler
from vyper.exceptions import TypeMismatchException


fail_list = [
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: int128}[2], b: int128}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: decimal}[2], b: int128}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: int128}[3], b: int128, c: int128}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: int128}[3]}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: int128}, b: int128}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.nom = self.mom.b
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.mom = {a: self.nom, b: 5.5}
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: decimal}[3]
@public
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.mom = {a: self.nom, b: self.nom}
    """,
    """
nom: {a: {c: int128}[int128], b: int128}
@public
def foo():
    reset(self.nom)
    """,
    """
nom: {a: {c: int128}[int128], b: int128}
@public
def foo():
    self.nom = {a: [{c: 5}], b: 7}
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = {0: 5, 1: 7, 2: 9}
    """,
    """
bar: int128[3]
@public
def foo():
    self.bar = {a: 5, b: 7, c: 9}
    """,
    """
@public
def foo() -> int128:
    return {cow: 5, dog: 7}
    """,
    """
x: {cow: int128, cor: int128}
@public
def foo():
    self.x.cof = 1
    """,
    """
b: {foo: int128}
@public
def foo():
    self.b = {foo: 1, foo: 2}
    """,
    """
b: {foo: int128, bar: int128}
@public
def foo():
    x = self.b.cow
    """,
    """
b: {foo: int128, bar: int128}
@public
def foo():
    x = self.b[0]
    """,
]


@pytest.mark.parametrize('bad_code', fail_list)
def test_block_fail(bad_code):
        with raises(TypeMismatchException):
            compiler.compile(bad_code)


valid_list = [
    """
mom: {a: {c: int128}[3], b: int128}
nom: {a: {c: decimal}[3], b: int128}
@public
def foo():
    self.nom = self.mom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.nom = self.mom.a
    """,
    """
nom: {a: {c: int128}[int128], b: int128}
@public
def foo():
    self.nom.a[135] = {c: 6}
    self.nom.b = 9
    """,
    """
nom: {c: int128}[3]
@public
def foo():
    mom: {a: {c: int128}[3], b: int128}
    mom.a = self.nom
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
mom: {a: {c: int128}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    empty: {c: int128}[3]
    self.mom = {a: empty, b: 5}
    """,
    """
mom: {a: {c: int128}[3], b: int128}
@public
def foo():
    nom: {c: int128}[3]
    self.mom = {a: nom, b: 5}
    """,
    """
mom: {a: {c: decimal}[3], b: int128}
nom: {c: int128}[3]
@public
def foo():
    self.mom = {a: self.nom, b: 5}
    """,
    """
b: {foo: int128, bar: int128}
@public
def foo():
    x: int128 = self.b.bar
    """,
    """
x: {bar: int128, baz: int128}
    """,
]


@pytest.mark.parametrize('good_code', valid_list)
def test_block_success(good_code):
    assert compiler.compile(good_code) is not None
