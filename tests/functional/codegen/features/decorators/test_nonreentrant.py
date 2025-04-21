import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation, FunctionDeclarationException

# TODO test functions in this module across all evm versions
# once we have cancun support.


def test_nonreentrant_decorator(get_contract, tx_failed):
    malicious_code = """
interface ProtectedContract:
    def protected_function(callback_address: address): nonpayable

@external
def do_callback():
    extcall ProtectedContract(msg.sender).protected_function(self)
    """

    protected_code = """
interface Callbackable:
    def do_callback(): nonpayable

@external
@nonreentrant
def protected_function(c: Callbackable):
    extcall c.do_callback()

# add a default function so we know the callback didn't fail for any reason
# besides nonreentrancy
@external
def __default__():
    pass
    """
    contract = get_contract(protected_code)
    malicious = get_contract(malicious_code)

    with tx_failed():
        contract.protected_function(malicious.address)


def test_nonreentrant_view_function(get_contract, tx_failed):
    malicious_code = """
interface ProtectedContract:
    def protected_function(): nonpayable
    def protected_view_fn() -> uint256: view

@external
def do_callback() -> uint256:
    return staticcall ProtectedContract(msg.sender).protected_view_fn()
    """

    protected_code = """
interface Callbackable:
    def do_callback(): nonpayable

@external
@nonreentrant
def protected_function(c: Callbackable):
    extcall c.do_callback()

@external
@nonreentrant
@view
def protected_view_fn() -> uint256:
    return 10

# add a default function so we know the callback didn't fail for any reason
# besides nonreentrancy
@external
def __default__():
    pass
    """
    contract = get_contract(protected_code)
    malicious = get_contract(malicious_code)

    with tx_failed():
        contract.protected_function(malicious.address)


def test_multi_function_nonreentrant(get_contract, tx_failed):
    malicious_code = """
interface ProtectedContract:
    def unprotected_function(val: String[100], do_callback: bool): nonpayable
    def protected_function(val: String[100], do_callback: bool): nonpayable
    def special_value() -> String[100]: nonpayable

@external
def updated():
    extcall ProtectedContract(msg.sender).unprotected_function('surprise!', False)

@external
def updated_protected():
    # This should fail.
    extcall ProtectedContract(msg.sender).protected_function('surprise protected!', False)
    """

    protected_code = """
interface Callback:
    def updated(): nonpayable
    def updated_protected(): nonpayable

interface Self:
    def protected_function(val: String[100], do_callback: bool) -> uint256: nonpayable
    def protected_function2(val: String[100], do_callback: bool) -> uint256: nonpayable
    def protected_view_fn() -> String[100]: view

special_value: public(String[100])
callback: public(Callback)

@external
def set_callback(c: address):
    self.callback = Callback(c)

@external
@nonreentrant
def protected_function(val: String[100], do_callback: bool) -> uint256:
    self.special_value = val

    if do_callback:
        extcall self.callback.updated_protected()
        return 1
    else:
        return 2

@external
@nonreentrant
def protected_function2(val: String[100], do_callback: bool) -> uint256:
    self.special_value = val
    if do_callback:
        # call other function with same nonreentrancy key
        extcall Self(self).protected_function(val, False)
        return 1
    return 2

@external
@nonreentrant
def protected_function3(val: String[100], do_callback: bool) -> uint256:
    self.special_value = val
    if do_callback:
        # call other function with same nonreentrancy key
        assert self.special_value == staticcall Self(self).protected_view_fn()
        return 1
    return 2


@external
@nonreentrant
@view
def protected_view_fn() -> String[100]:
    return self.special_value

@external
def unprotected_function(val: String[100], do_callback: bool):
    self.special_value = val

    if do_callback:
        extcall self.callback.updated()

# add a default function so we know the callback didn't fail for any reason
# besides nonreentrancy
@external
def __default__():
    pass
    """
    contract = get_contract(protected_code)
    malicious = get_contract(malicious_code)

    contract.set_callback(malicious.address)
    assert contract.callback() == malicious.address

    # Test unprotected function.
    contract.unprotected_function("some value", True)
    assert contract.special_value() == "surprise!"

    # Test protected function.
    contract.protected_function("some value", False)
    assert contract.special_value() == "some value"
    assert contract.protected_view_fn() == "some value"

    with tx_failed():
        contract.protected_function("zzz value", True)

    contract.protected_function2("another value", False)
    assert contract.special_value() == "another value"

    with tx_failed():
        contract.protected_function2("zzz value", True)

    contract.protected_function3("another value", False)
    assert contract.special_value() == "another value"

    with tx_failed():
        contract.protected_function3("zzz value", True)


def test_nonreentrant_decorator_for_default(env, get_contract, tx_failed):
    calling_contract_code = """
@external
def send_funds(_amount: uint256):
    # raw_call() is used to overcome gas limit of send()
    response: Bytes[32] = raw_call(
        msg.sender,
        _abi_encode(msg.sender, _amount, method_id=method_id("transfer(address,uint256)")),
        max_outsize=32,
        value=_amount
    )

@external
@payable
def __default__():
    pass
    """

    reentrant_code = """
interface Callback:
    def send_funds(_amount: uint256): nonpayable

special_value: public(String[100])
callback: public(Callback)

@external
def set_callback(c: address):
    self.callback = Callback(c)

@external
@payable
@nonreentrant
def protected_function(val: String[100], do_callback: bool) -> uint256:
    self.special_value = val
    _amount: uint256 = msg.value
    send(self.callback.address, msg.value)

    if do_callback:
        extcall self.callback.send_funds(_amount)
        return 1
    else:
        return 2

@external
@payable
def unprotected_function(val: String[100], do_callback: bool):
    self.special_value = val
    _amount: uint256 = msg.value
    send(self.callback.address, msg.value)

    if do_callback:
        extcall self.callback.send_funds(_amount)

@external
@payable
@nonreentrant
def __default__():
    pass
    """

    reentrant_contract = get_contract(reentrant_code)
    calling_contract = get_contract(calling_contract_code)

    reentrant_contract.set_callback(calling_contract.address)
    assert reentrant_contract.callback() == calling_contract.address

    # Test unprotected function without callback.
    env.set_balance(env.deployer, 10**6)
    reentrant_contract.unprotected_function("some value", False, value=1000)
    assert reentrant_contract.special_value() == "some value"
    assert env.get_balance(reentrant_contract.address) == 0
    assert env.get_balance(calling_contract.address) == 1000

    # Test unprotected function with callback to default.
    reentrant_contract.unprotected_function("another value", True, value=1000)
    assert reentrant_contract.special_value() == "another value"
    assert env.get_balance(reentrant_contract.address) == 1000
    assert env.get_balance(calling_contract.address) == 1000

    # Test protected function without callback.
    reentrant_contract.protected_function("surprise!", False, value=1000)
    assert reentrant_contract.special_value() == "surprise!"
    assert env.get_balance(reentrant_contract.address) == 1000
    assert env.get_balance(calling_contract.address) == 2000

    # Test protected function with callback to default.
    with tx_failed():
        reentrant_contract.protected_function("zzz value", True, value=1000)


def test_disallow_on_init_function(get_contract):
    # nonreentrant has no effect when used on the __init__ fn
    # however, should disallow its usage regardless
    code = """

@external
@nonreentrant
def __init__():
    foo: uint256 = 0
"""
    with pytest.raises(FunctionDeclarationException):
        get_contract(code)


def _error_template(target, caller):
    msg = f"Cannot call `{target}` since it is `@nonreentrant` and reachable"
    msg += f" from `{caller}`, which is also marked `@nonreentrant`"
    return msg


successive_nonreentrant = [
    # external nonreentrant calls private nonreentrant
    (
        """
@external
@nonreentrant
def foo() -> uint256:
    return self.bar()

@nonreentrant
def bar() -> uint256:
    return 1
    """,
        _error_template("bar", "foo"),
    ),
    # external nonreentrant calls private which calls private nonreentrant
    (
        """
@external
@nonreentrant
def foo() -> uint256:
    return self.bar()

def bar() -> uint256:
    return self.baz()

@nonreentrant
def baz() -> uint256:
    return 1
""",
        _error_template("baz", "foo"),
    ),
    # private nonreentrant calls private nonreentrant
    (
        """
@nonreentrant
def bar() -> uint256:
    return self.baz()

@nonreentrant
def baz() -> uint256:
    return 1
    """,
        _error_template("baz", "bar"),
    ),
    # private nonreentrant calls private which call private nonreentrant
    (
        """
@nonreentrant
def foo() -> uint256:
    return self.bar()

def bar() -> uint256:
    return self.baz()

@nonreentrant
def baz() -> uint256:
    return 1
   """,
        _error_template("baz", "foo"),
    ),
]


@pytest.mark.parametrize("failing_code, message", successive_nonreentrant)
def test_call_nonreentrant_from_nonreentrant(get_contract, failing_code, message):
    with pytest.raises(CallViolation, match=message):
        compile_code(failing_code)


def test_call_nonreentrant_lib_from_nonreentrant(get_contract, make_input_bundle):
    lib1 = """
@nonreentrant
def baz():
    pass
        """
    lib2 = """
import lib1

uses: lib1

counter: uint256

def bar():
    lib1.baz()
        """
    main = """
import lib1
import lib2

initializes: lib1
initializes: lib2[lib1:=lib1]

@nonreentrant
@external
def foo():
    lib2.bar()
        """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})
    with pytest.raises(CallViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    msg = _error_template("baz", "foo")
    assert e.value._message == msg
