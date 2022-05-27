import pytest

from vyper import compiler
from vyper.exceptions import (
    ArgumentException,
    InvalidReference,
    StructureException,
    TypeMismatch,
    UnknownAttribute,
)

valid_list = [
    """
enum Action:
    buy
    sale
    """,
    """
enum Action:
    buy
    sale
@external
def run() -> Action:
    return Action.buy
    """,
    """
enum Action:
    buy
    sale

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
