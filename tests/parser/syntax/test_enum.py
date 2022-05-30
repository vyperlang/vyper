import pytest

from vyper import compiler
from vyper.exceptions import (
    NamespaceCollision,
    EnumDeclarationException,
)

fail_list = [
    (
        """
event Action:
    pass

enum Action:
    buy
    sell
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
    buy
    buy
    """,
        EnumDeclarationException,
    ),
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_interfaces_fail(bad_code):
    with pytest.raises(bad_code[1]):
        compiler.compile_code(bad_code[0])


valid_list = [
    """
enum Action:
    buy
    sell
    """,
    """
enum Action:
    buy
    sell
@external
def run() -> Action:
    return Action.buy
    """,
    """
enum Action:
    buy
    sell

struct Order:
    action: Action
    amount: uint256

@external
def run() -> Order:
    return Order({
        action: Action.buy,
        amount: 10**18
        })
    """,
]


@pytest.mark.parametrize("good_code", valid_list)
def test_enum_success(good_code):
    assert compiler.compile_code(good_code) is not None
