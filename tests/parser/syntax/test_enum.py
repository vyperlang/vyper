import pytest

from vyper import compiler

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
