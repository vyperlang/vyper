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


nonpayable_code = [
    """
# single function, nonpayable
@external
def foo() -> bool:
    return True
    """,
    """
# multiple functions, one is payable
@external
def foo() -> bool:
    return True

@payable
@external
def bar() -> bool:
    return True
    """,
    """
# multiple functions, nonpayable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True
    """,
    """
# multiple functions, nonpayable (view)
@external
def foo() -> bool:
    return True

@view
@external
def bar() -> bool:
    return True
    """,
    """
# payable init function
@external
@payable
def __init__():
    a: int128 = 1

@external
def foo() -> bool:
    return True
    """,
    """
# payable default function
@external
@payable
def __default__():
    a: int128 = 1

@external
def foo() -> bool:
    return True
    """,
]


@pytest.mark.parametrize("code", nonpayable_code)
def test_nonpayable_runtime_assertion(assert_tx_failed, get_contract, code):
    c = get_contract(code)

    c.foo(transact={"value": 0})
    assert_tx_failed(lambda: c.foo(transact={"value": 10 ** 18}))


payable_code = [
    """
# single function, payable
@payable
@external
def foo() -> bool:
    return True
    """,
    """
# multiple functions, one is payable
@payable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True
    """,
    """
# multiple functions, payable
@payable
@external
def foo() -> bool:
    return True

@payable
@external
def bar() -> bool:
    return True
    """,
    """
# multiple functions, one nonpayable (view)
@payable
@external
def foo() -> bool:
    return True

@view
@external
def bar() -> bool:
    return True
    """,
    """
# init function
@external
def __init__():
    a: int128 = 1

@payable
@external
def foo() -> bool:
    return True
    """,
    """
# default function
@external
def __default__():
    a: int128 = 1

@external
@payable
def foo() -> bool:
    return True
    """,
]


@pytest.mark.parametrize("code", payable_code)
def test_payable_runtime_assertion(get_contract, code):
    c = get_contract(code)

    c.foo(transact={"value": 10 ** 18})
    c.foo(transact={"value": 0})
