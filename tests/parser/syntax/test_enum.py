import pytest

from vyper import compiler
from vyper.exceptions import (
    EnumDeclarationException,
    InvalidOperation,
    NamespaceCollision,
    TypeMismatch,
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
def foo(x: Roles) -> bool:
    return x >= Roles.STAFF
    """,
        InvalidOperation,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_interfaces_fail(bad_code):
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
]


@pytest.mark.parametrize("good_code", valid_list)
def test_enum_success(good_code):
    assert compiler.compile_code(good_code) is not None
