import pytest

from vyper import compiler
from vyper.exceptions import (
    EnumDeclarationException,
    InvalidOperation,
    NamespaceCollision,
    StructureException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    (
        """
event Action:
    pass

enum Action:
    BUY
    SELL
    """,
        NamespaceCollision,
    ),
    (
        """
enum Action:
    pass
    """,
        EnumDeclarationException,
    ),
    (
        """
enum Action:
    BUY
    BUY
    """,
        EnumDeclarationException,
    ),
    ("enum Foo:\n" + "\n".join([f"    member{i}" for i in range(257)]), EnumDeclarationException),
    (
        """
enum Roles:
    USER
    STAFF
    ADMIN

@external
def foo(x: Roles) -> bool:
    return x in [Roles.USER, Roles.ADMIN]
    """,
        TypeMismatch,
    ),
    (
        """
enum Roles:
    USER
    STAFF
    ADMIN

@external
def foo(x: Roles) -> Roles:
    return x.USER  # can't dereference on enum instance
    """,
        StructureException,
    ),
    (
        """
enum Roles:
    USER
    STAFF
    ADMIN

@external
def foo(x: Roles) -> bool:
    return x >= Roles.STAFF
    """,
        InvalidOperation,
    ),
    (
        """
enum Functions:
    def foo():nonpayable
    """,
        EnumDeclarationException,
    ),
    (
        """
enum Numbers:
    a:constant(uint256) = a
    """,
        EnumDeclarationException,
    ),
    (
        """
enum Numbers:
    12
    """,
        EnumDeclarationException,
    ),
    (
        """
enum Roles:
    ADMIN
    USER

@external
def foo() -> Roles:
    return Roles.GUEST
    """,
        UnknownAttribute,
    ),
    (
        """
enum A:
    a
enum B:
    a
    b

@internal
def foo():
    a: A = B.b
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_fail_cases(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
enum Action:
    BUY
    SELL
    """,
    """
enum Action:
    BUY
    SELL
@external
def run() -> Action:
    return Action.BUY
    """,
    """
enum Action:
    BUY
    SELL

struct Order:
    action: Action
    amount: uint256

@external
def run() -> Order:
    return Order({
        action: Action.BUY,
        amount: 10**18
        })
    """,
    "enum Foo:\n" + "\n".join([f"    member{i}" for i in range(256)]),
    """
a: constant(uint256) = 1

enum A:
    a
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_enum_success(good_code):
    assert compiler.compile_code(good_code) is not None
