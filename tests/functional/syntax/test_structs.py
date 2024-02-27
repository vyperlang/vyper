import warnings

import pytest

from vyper import compiler
from vyper.exceptions import (
    InstantiationException,
    StructureException,
    SyntaxException,
    TypeMismatch,
    UnknownAttribute,
    VariableDeclarationException,
)

fail_list = [
    """
struct A:
    x: int128
a: A
@external
def foo():
    self.a = A(1)
    """,
    (
        """
struct A:
    x: int128
a: A
@external
def foo():
    self.a = A(x=1, y=2)
    """,
        UnknownAttribute,
    ),
    """
struct A:
    x: int128
    y: int128
a: A
@external
def foo():
    self.a = A(x=1)
    """,
    """
struct A:
    x: int128
struct B:
    x: int128
a: A
b: B
@external
def foo():
    self.a = A(self.b)
    """,
    """
struct A:
    x: int128
a: A
b: A
@external
def foo():
    self.a = A(self.b)
    """,
    """
struct A:
    x: int128
    y: int128
a: A
@external
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
@external
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
@external
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
@external
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
@external
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
@external
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
@external
def foo():
    self.nom = Nom(self.mom)
    """,
    """
struct Foo:
    a: uint256
    b: uint256

@external
def foo(i: uint256, j: uint256):
    f: Foo = Foo(i, b=j)
    """,
    (
        """
struct Mom:
    a: int128
struct Nom:
    a: int128
mom: Mom
nom: Nom
@external
def foo():
    self.nom = self.mom # require cast
    """,
        TypeMismatch,
    ),
    """
struct Mom:
    a: int128
struct Nom:
    b: int128
mom: Mom
nom: Nom
@external
def foo():
    self.nom = Nom(self.mom)
    """,
    (
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
@external
def foo():
    self.nom = self.mom # require cast
    """,
        TypeMismatch,
    ),
    (
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
@external
def foo():
    self.nom = self.mom.b
    """,
        TypeMismatch,
    ),
    (
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
@external
def foo():
    self.mom = Mom(a=self.nom, b=5.5)
    """,
        TypeMismatch,
    ),
    (
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
@external
def foo():
    self.mom = Mom(a=self.nom, b=5)
    """,
        TypeMismatch,
    ),
    (
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
@external
def foo():
    self.mom = Mom(a=self.nom, b=self.nom)
    """,
        TypeMismatch,
    ),
    (
        """
struct C:
    c: int128
struct Nom:
    a: HashMap[int128, C]
    b: int128
    """,
        InstantiationException,
    ),
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
@external
def foo():
    self.nom = Nom(self.mom)
    """,
    (
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
@external
def foo():
    self.mom = Mom(a=self.nom, b=5)
    """,
        TypeMismatch,
    ),
    (
        """
struct Bar:
    a: int128
    b: int128
    c: int128
bar: int128[3]
@external
def foo():
    self.bar = Bar(0=5, 1=7, 2=9)
    """,
        SyntaxException,
    ),
    (
        """
struct Bar:
    a: int128
    b: int128
    c: int128
bar: int128[3]
@external
def foo():
    self.bar = Bar(a=5, b=7, c=9)
    """,
        TypeMismatch,
    ),
    (
        """
struct Farm:
    cow: int128
    dog: int128
@external
def foo() -> int128:
    f: Farm = Farm(cow=5, dog=7)
    return f
    """,
        TypeMismatch,
    ),
    (
        """
struct X:
    cow: int128
    cor: int128
x: X
@external
def foo():
    self.x.cof = 1
    """,
        UnknownAttribute,
    ),
    (
        """
struct B:
    foo: int128
b: B
@external
def foo():
    self.b = B(foo=1, foo=2)
    """,
        UnknownAttribute,
    ),
    (
        """
struct B:
    foo: int128
    bar: int128
b: B
@external
def foo():
    x: int128 = self.b.cow
    """,
        UnknownAttribute,
    ),
    (
        """
struct B:
    foo: int128
    bar: int128
b: B
@external
def foo():
    x: int128 = self.b[0]
    """,
        StructureException,
    ),
    (
        """
struct Foo:
    a: uint256

@external
def foo():
    Foo(a=1)
    """,
        StructureException,
    ),
    (
        """
event Foo:
    a: uint256

struct Bar:
    a: Foo
    """,
        InstantiationException,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_block_fail(bad_code):
    if isinstance(bad_code, tuple):
        with pytest.raises(bad_code[1]):
            compiler.compile_code(bad_code[0])
    else:
        with pytest.raises(VariableDeclarationException):
            compiler.compile_code(bad_code)


valid_list = [
    """
struct A:
    x: int128
a: A
@external
def foo():
    self.a = A(x=1)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
nom: C[3]
@external
def foo():
    self.nom = self.mom.a
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
nom: C[3]
@external
def foo():
    mom: Mom = Mom(a=[C(c=0), C(c=0), C(c=0)], b=0)
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
@external
def foo():
    self.mom = Mom(a=self.nom, b=5)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
nom: C[3]
@external
def foo():
    self.mom = Mom(a=self.nom, b=5)
    """,
    """
struct C:
    c: int128
struct Mom:
    a: C[3]
    b: int128
mom: Mom
@external
def foo():
    nom: C[3] = [C(c=0), C(c=0), C(c=0)]
    self.mom = Mom(a=nom, b=5)
    """,
    """
struct B:
    foo: int128
    bar: int128
b: B
@external
def foo():
    x: int128 = self.b.bar
    """,
    """
struct X:
    bar: int128
    baz: int128
x: X
    """,
    """
struct X:
    x: int128
    y: int128
struct A:
    a: X
    b: uint256
struct C:
    c: A
    d: bool
@external
def get_y() -> int128:
    return C(c=A(a=X(x=1, y=-1), b=777), d=True).c.a.y - 10
    """,
    """
struct X:
    x: int128
    y: int128
struct A:
    a: X
    b: uint256
struct C:
    c: A
    d: bool
FOO: constant(C) = C(c=A(a=X(x=1, y=-1), b=777), d=True)
@external
def get_y() -> int128:
    return FOO.c.a.y - 10
    """,
    """
struct C:
    a: uint256
    b: uint256

@external
def foo():
    bar: C = C(a=1, b=block.timestamp)
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_block_success(good_code):
    assert compiler.compile_code(good_code) is not None


def test_old_constructor_syntax():
    # backwards compatibility for vyper <0.4.0
    code = """
struct A:
    x: int128
a: A
@external
def foo():
    self.a = A({x: 1})
    """
    with warnings.catch_warnings(record=True) as w:
        assert compiler.compile_code(code) is not None

        expected = "Instantiating a struct using a dictionary is deprecated "
        expected += "as of v0.4.0 and will be disallowed in a future release. "
        expected += "Use kwargs instead e.g. Foo(a=1, b=2)"

        assert len(w) == 1
        assert str(w[0].message).startswith(expected)
