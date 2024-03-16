import pytest

from vyper.compiler import compile_code
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
    extcall self.piggy.deposit()
    """,
        # You don't have to send value in a payable call
        """
interface PiggyBank:
    def deposit(): payable

piggy: PiggyBank

@external
def foo():
    extcall self.piggy.deposit()
    """,
    ],
)
def test_payable_call_compiles(source, get_contract):
    _ = compile_code(source)


@pytest.mark.parametrize(
    "source",
    [
        """
interface PiggyBank:
    def deposit(): nonpayable

piggy: PiggyBank

@external
def foo():
    # sends value to nonpayable function
    extcall self.piggy.deposit(value=self.balance)
    """
    ],
)
def test_payable_compile_fail(source, get_contract, assert_compile_failed):
    with pytest.raises(CallViolation):
        compile_code(source)


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
# multiple functions and default func, nonpayable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True

@external
def __default__():
    pass
    """,
    """
    # multiple functions and default func, payable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True

@external
@payable
def __default__():
    pass
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
@deploy
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
    """
# payable default function and other function
@external
@payable
def __default__():
    a: int128 = 1

@external
def foo() -> bool:
    return True

@external
@payable
def bar() -> bool:
    return True
    """,
    """
# several functions, one payable
@external
def foo() -> bool:
    return True

@payable
@external
def bar() -> bool:
    return True

@external
def baz() -> bool:
    return True
    """,
]


@pytest.mark.parametrize("code", nonpayable_code)
def test_nonpayable_runtime_assertion(w3, keccak, tx_failed, get_contract, code):
    c = get_contract(code)

    c.foo(transact={"value": 0})
    sig = keccak("foo()".encode()).hex()[:10]
    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "data": sig, "value": 10**18})


payable_code = [
    """
# single function, payable
@payable
@external
def foo() -> bool:
    return True
    """,
    """
# two functions, one is payable
@payable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True
    """,
    """
# two functions, payable
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
# two functions, one nonpayable (view)
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
# several functions, all payable
@payable
@external
def foo() -> bool:
    return True

@payable
@external
def bar() -> bool:
    return True

@payable
@external
def baz() -> bool:
    return True
    """,
    """
# several functions, one payable
@payable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True

@external
def baz() -> bool:
    return True
    """,
    """
# several functions, two payable
@payable
@external
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True

@payable
@external
def baz() -> bool:
    return True
    """,
    """
# init function
@deploy
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
    """
# payable default function
@external
@payable
def __default__():
    a: int128 = 1

@external
@payable
def foo() -> bool:
    return True
    """,
    """
# payable default function and nonpayable other function
@external
@payable
def __default__():
    a: int128 = 1

@external
@payable
def foo() -> bool:
    return True

@external
def bar() -> bool:
    return True
    """,
]


@pytest.mark.parametrize("code", payable_code)
def test_payable_runtime_assertion(get_contract, code):
    c = get_contract(code)

    c.foo(transact={"value": 10**18})
    c.foo(transact={"value": 0})


def test_payable_default_func_invalid_calldata(get_contract, w3):
    code = """
@external
def foo() -> bool:
    return True

@payable
@external
def __default__():
    pass
    """

    c = get_contract(code)
    w3.eth.send_transaction({"to": c.address, "value": 100, "data": "0x12345678"})


def test_nonpayable_default_func_invalid_calldata(get_contract, w3, tx_failed):
    code = """
@external
@payable
def foo() -> bool:
    return True

@external
def __default__():
    pass
    """

    c = get_contract(code)
    w3.eth.send_transaction({"to": c.address, "value": 0, "data": "0x12345678"})
    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "value": 100, "data": "0x12345678"})


def test_batch_nonpayable(get_contract, w3, tx_failed):
    code = """
@external
def foo() -> bool:
    return True

@external
def __default__():
    pass
    """

    c = get_contract(code)
    w3.eth.send_transaction({"to": c.address, "value": 0, "data": "0x12345678"})
    data = bytes([1, 2, 3, 4])
    for i in range(5):
        calldata = "0x" + data[:i].hex()
        with tx_failed():
            w3.eth.send_transaction({"to": c.address, "value": 100, "data": calldata})
