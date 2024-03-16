import pytest

from vyper import compiler
from vyper.exceptions import (
    FlagDeclarationException,
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

flag Action:
    BUY
    SELL
    """,
        NamespaceCollision,
    ),
    (
        """
flag Action:
    pass
    """,
        FlagDeclarationException,
    ),
    (
        """
flag Action:
    BUY
    BUY
    """,
        FlagDeclarationException,
    ),
    ("flag Foo:\n" + "\n".join([f"    member{i}" for i in range(257)]), FlagDeclarationException),
    (
        """
flag Roles:
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
flag Roles:
    USER
    STAFF
    ADMIN

@external
def foo(x: Roles) -> Roles:
    return x.USER  # can't dereference on flag instance
    """,
        StructureException,
    ),
    (
        """
flag Roles:
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
flag Functions:
    def foo():nonpayable
    """,
        FlagDeclarationException,
    ),
    (
        """
flag Numbers:
    a:constant(uint256) = a
    """,
        FlagDeclarationException,
    ),
    (
        """
flag Numbers:
    12
    """,
        FlagDeclarationException,
    ),
    (
        """
flag Roles:
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
flag A:
    a
flag B:
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
flag Action:
    BUY
    SELL
    """,
    """
flag Action:
    BUY
    SELL
@external
def run() -> Action:
    return Action.BUY
    """,
    """
flag Action:
    BUY
    SELL

struct Order:
    action: Action
    amount: uint256

@external
def run() -> Order:
    return Order(
        action=Action.BUY,
        amount=10**18
        )
    """,
    "flag Foo:\n" + "\n".join([f"    member{i}" for i in range(256)]),
    """
a: constant(uint256) = 1

flag A:
    a
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_flag_success(good_code):
    assert compiler.compile_code(good_code) is not None
