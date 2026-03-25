import contextlib

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation, FunctionDeclarationException, StructureException

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


def test_reentrant_decorator(get_contract, tx_failed):
    malicious_code = """
interface ProtectedContract:
    def protected_function(callback_address: address): nonpayable

interface UnprotectedContract:
    def unprotected_function(callback_address: address, continue_recursion: bool): nonpayable

@external
def do_protected_callback():
    extcall ProtectedContract(msg.sender).protected_function(self)

@external
def do_unprotected_callback():
    extcall UnprotectedContract(msg.sender).unprotected_function(self, False)
    """

    protected_code = """
#pragma nonreentrancy on

interface Callbackable:
    def do_protected_callback(): nonpayable
    def do_unprotected_callback(): nonpayable

@external
@reentrant
def unprotected_function(c: Callbackable, continue_recursion: bool = True) -> uint256:
    if continue_recursion:
        extcall c.do_unprotected_callback()
    return 1

@external
def protected_function(c: Callbackable) -> uint256:
    extcall c.do_protected_callback()
    return 2

# add a default function so we know the callback didn't fail for any reason
# besides nonreentrancy
@external
def __default__():
    pass
    """

    benign_code = """
@external
def __default__():
    pass
    """

    contract = get_contract(protected_code)
    malicious = get_contract(malicious_code)
    benign = get_contract(benign_code)

    assert contract.unprotected_function(malicious.address) == 1
    with tx_failed():
        contract.protected_function(malicious.address)

    assert contract.unprotected_function(benign.address) == 1
    assert contract.protected_function(benign.address) == 2


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


def test_nonreentrant_internal(get_contract):
    code = """
# pragma nonreentrancy on

def foo():
    u: uint256 = 1

@external
def bar():
    self.foo()
    """
    c = get_contract(code)

    c.bar()


# external function is reentrant so it shouldn't
# lock and the call to foo should pass
def test_nonreentrant_internal2(get_contract, tx_failed):
    code = """
# pragma nonreentrancy on

@nonreentrant
def foo():
    u: uint256 = 1

@external
@reentrant
def bar():
    self.foo()
    """
    c = get_contract(code)

    c.bar()


# nonreentrant pragma is off, external function
# shouldn't lock the lock
def test_nonreentrant_internal3(get_contract):
    code = """
# pragma nonreentrancy off

@nonreentrant
def foo():
    u: uint256 = 1

@external
def bar():
    self.foo()
    """
    c = get_contract(code)
    c.bar()


# external function is reentrant so it shouldn't
# lock, the internal is nonreentrant, so upon
# reentrancy the call should fail
# the bool is added to ensure we don't fail on infinite
# recursion
def test_nonreentrant_internal4(get_contract, tx_failed):
    code = """
# pragma nonreentrancy on

interface Self:
    def bar(end: bool): nonpayable

@nonreentrant
def foo(end: bool):
    if not end:
        extcall Self(self).bar(True)

@external
@reentrant
def bar(end: bool):
    self.foo(end)
    """
    c = get_contract(code)

    with tx_failed():
        c.bar(False)


# nonreentrant pragma is off, external function
# should be reentrant
def test_function_is_reentrant(get_contract):
    code = """
# pragma nonreentrancy off

interface Self:
    def bar(end: bool): nonpayable

@external
def bar(end: bool):
    if not end:
        extcall Self(self).bar(True)
    """
    c = get_contract(code)
    c.bar(False)


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


# the pragma shouldn't have an effect on the __init__
# function and thus `foo` should be callable
def test_nonreentrant_pragma_with_init(get_contract):
    code = """
# pragma nonreentrancy on

@deploy
def __init__():
    self.foo()

@nonreentrant
def foo():
    pass
"""
    _ = get_contract(code)


# function can't be marked nonreentrant
# while the nonreentrant pragma is on
def test_disallow_nonreentrant_while_pragma(get_contract):
    code = """
# pragma nonreentrancy on

@external
@nonreentrant
def bar():
    pass
"""
    with pytest.raises(StructureException):
        get_contract(code)


# foo in main module has reentrancy on, bar in lib1 has reentrancy off
# call bar from foo via extcall and ensure it passes
@pytest.mark.parametrize("pragma_string", ["", "# pragma nonreentrancy off"])
def test_multi_module_nonreentrant_pragma(make_input_bundle, get_contract, pragma_string):
    lib1 = f"""
{pragma_string}

@external
def bar():
    pass

    """
    main = """
# pragma nonreentrancy on

import lib1

interface Self:
    def bar(): nonpayable

exports: lib1.bar

@external
def foo():
    extcall Self(self).bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)

    c.foo()


# foo in main module has reentrancy on, bar in lib1 has reentrancy on
# call bar from foo via extcall and ensure it fail
def test_multi_module_nonreentrant_pragma2(make_input_bundle, get_contract, tx_failed):
    lib1 = """
# pragma nonreentrancy on

@external
def bar():
    pass

    """
    main = """
# pragma nonreentrancy on

import lib1

interface Self:
    def bar(): nonpayable

initializes: lib1
exports: lib1.bar

@external
def foo():
    extcall Self(self).bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)

    with tx_failed():
        c.foo()


# there's no reason to protect immutable and constant variable
# getters, they should be reentrant.
# this test also tests the behavior inside of a submodule
def test_pragma_with_immutables_and_constants(make_input_bundle, get_contract, tx_failed):
    lib1 = """
# pragma nonreentrancy on

a: public(constant(uint256)) = 333
b: public(immutable(uint256))

@deploy
def __init__():
    b = 666

    """
    main = """
# pragma nonreentrancy on

import lib1
initializes: lib1

interface Self:
    def a() -> uint256: nonpayable
    def b() -> uint256: nonpayable

exports: lib1.a
exports: lib1.b

@deploy
def __init__():
    lib1.__init__()

@external
def foo():
    res: uint256 = extcall Self(self).a()
    assert res == 333
    res = extcall Self(self).b()
    assert res == 666
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)

    c.foo()


# foo in main module has reentrancy on, bar in lib1 off because
# that's the default for internal functions
# call bar from foo via extcall and ensure it succeeds
def test_multi_module_nonreentrant_pragma3(make_input_bundle, get_contract, tx_failed):
    lib1 = """
# pragma nonreentrancy on

def bar():
    pass

    """
    main = """
# pragma nonreentrancy on

import lib1

interface Self:
    def bar(): nonpayable

initializes: lib1

@external
def foo():
    lib1.bar()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)

    c.foo()


# main module's reentrancy pragma shouldn't
# affect lib1's reentrancy settings
# lib1.bar should thus be nonreentrant only if
# the lib1's nonreentrancy pragma is on
@pytest.mark.parametrize("lib_pragma_state", ["on", "off"])
@pytest.mark.parametrize("main_pragma_state", ["on", "off"])
def test_multi_module_nonreentrant_pragma4(
    make_input_bundle, get_contract, tx_failed, lib_pragma_state, main_pragma_state
):
    lib1 = f"""
# pragma nonreentrancy {lib_pragma_state}

interface Self:
    def bar(end: bool): nonpayable

@external
def bar(end: bool):
    if not end:
        extcall Self(self).bar(True)
    """
    main = f"""
# pragma nonreentrancy {main_pragma_state}

import lib1

initializes: lib1

exports: lib1.bar
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    c = get_contract(main, input_bundle=input_bundle)

    if lib_pragma_state == "on":
        with tx_failed():
            c.bar(False)


@pytest.mark.parametrize("lib1_pragma_state", ["on", "off"])
@pytest.mark.parametrize("lib2_pragma_state", ["on", "off"])
@pytest.mark.parametrize("main_pragma_state", ["on", "off"])
@pytest.mark.parametrize("call_target", ["foo", "bar", "baz"])
def test_multi_module_nonreentrant_pragma5(
    make_input_bundle,
    get_contract,
    tx_failed,
    lib1_pragma_state,
    lib2_pragma_state,
    main_pragma_state,
    call_target,
):
    interface = """
interface Self:
    def foo(end: bool): nonpayable
    def bar(end: bool): nonpayable
    def baz(end: bool): nonpayable
"""

    lib1 = f"""
# pragma nonreentrancy {lib1_pragma_state}

import lib2

initializes: lib2

exports: lib2.baz

{interface}

@external
def bar(end: bool):
    if not end:
        extcall Self(self).{call_target}(True)
    """
    lib2 = f"""
# pragma nonreentrancy {lib2_pragma_state}

{interface}

@external
def baz(end: bool):
    if not end:
        extcall Self(self).{call_target}(True)
        """
    main = f"""
# pragma nonreentrancy {main_pragma_state}

import lib1
import lib2

initializes: lib1

exports: lib1.bar
exports: lib1.baz

{interface}

@external
def foo(end: bool):
    if not end:
        extcall Self(self).{call_target}(True)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1, "lib2.vy": lib2})

    c = get_contract(main, input_bundle=input_bundle)

    funs = [c.foo, c.bar, c.baz]

    fun_to_reentrancy = {
        c.foo: main_pragma_state,
        c.bar: lib1_pragma_state,
        c.baz: lib2_pragma_state,
    }

    fn_lookup = {"foo": c.foo, "bar": c.bar, "baz": c.baz}
    target_fun = fn_lookup[call_target]

    for fun in funs:
        both_nonreentrant = fun_to_reentrancy[fun] == fun_to_reentrancy[target_fun] == "on"

        if both_nonreentrant:
            ctx = tx_failed
        else:
            # pass
            ctx = contextlib.nullcontext

        with ctx():
            fun(False)


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


def test_nonreentrant_pragma_reentrant_default(get_contract):
    code = """
# pragma nonreentrancy on

counter: public(uint256)

@external
def foo():
    success: bool = raw_call(self, b"", revert_on_failure=False)
    assert success
    assert self.counter == 1

@external
# nonreentrant by default
@reentrant
def __default__():
    self.counter += 1
    """
    c = get_contract(code)
    c.foo()
    assert c.counter() == 1


def test_nonreentrant_pragma_nonreentrant_default(get_contract):
    code = """
# pragma nonreentrancy on

counter: public(uint256)

@external
def foo():
    success: bool = raw_call(self, b"", revert_on_failure=False)
    assert not success
    assert self.counter == 0

#nonreentrant by default
@external
def __default__():
    self.counter += 1
    """
    c = get_contract(code)
    c.foo()
    assert c.counter() == 0


@pytest.mark.parametrize("mutability", ["@view", "@pure"])
def test_nonreentrant_pragma_view_and_pure(env, get_contract, mutability):
    code = f"""
# pragma nonreentrancy on

interface Self:
    def bar() -> uint256: view

@external
{mutability}
def bar() -> uint256:
    return 42

@external
@view
def foo() -> uint256:
    return staticcall Self(self).bar()
    """
    c = get_contract(code)
    assert c.foo() == 42


@pytest.mark.parametrize("mutability", ["@view", "@pure"])
def test_nonreentrant_pragma_view2(env, tx_failed, get_contract, mutability):
    code = f"""
# pragma nonreentrancy on

interface Self:
    def bar() -> uint256: pure

@external
{mutability}
def bar() -> uint256:
    return 42

@external
def foo() -> uint256:
    return staticcall Self(self).bar()
    """
    c = get_contract(code)

    if mutability == "@view":
        ctx = tx_failed
    else:
        ctx = contextlib.nullcontext

    with ctx():
        c.foo()


@pytest.mark.parametrize("public_var", ["reentrant(public(uint256))", "public(uint256)"])
def test_nonreentrant_getter(tx_failed, get_contract, public_var):
    code = f"""
# pragma nonreentrancy on

interface Self:
    def bar() -> uint256: view

@deploy
def __init__():
    self.bar = 42

bar: {public_var}

@external
def foo() -> uint256:
    return staticcall Self(self).bar()
    """
    c = get_contract(code)

    if public_var.startswith("reentrant"):
        assert c.foo() == 42
    else:
        with tx_failed():
            c.foo()


# TODO: maybe belongs in syntax tests
def test_nonreentrant_getter_pragma_off():
    code = """
# pragma nonreentrancy off

bar: reentrant(public(uint256))

"""
    msg = "reentrant() is not allowed without `pragma nonreentrancy on"
    with pytest.raises(StructureException) as e:
        compile_code(code)

    assert e.value.message.startswith(msg)


def test_nonreentrant_getter_pragma_off2(get_contract):
    code = """
# pragma nonreentrancy off

interface Self:
    def bar() -> uint256: view

@deploy
def __init__():
    self.bar = 42

bar: public(uint256)

@external
@nonreentrant
def foo() -> uint256:
    return staticcall Self(self).bar()
"""
    c = get_contract(code)

    assert c.foo() == 42
