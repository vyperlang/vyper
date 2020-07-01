import pytest

from vyper.exceptions import CallViolation


@pytest.mark.parametrize(
    "source",
    [
        """
interface PiggyBank:
    def deposit(): nonpayable

piggy: PiggyBank

@external
def foo():
    self.piggy.deposit()
    """,
        # You don't have to send value in a payable call
        """
interface PiggyBank:
    def deposit(): payable

piggy: PiggyBank

@external
def foo():
    self.piggy.deposit()
    """,
    ],
)
def test_payable_call_compiles(source, get_contract):
    get_contract(source)


@pytest.mark.parametrize(
    "source",
    [
        """
interface PiggyBank:
    def deposit(): nonpayable

piggy: PiggyBank

@external
def foo():
    self.piggy.deposit(value=self.balance)
    """,
    ],
)
def test_payable_compile_fail(source, get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(source), CallViolation,
    )
