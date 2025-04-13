from typing import Any

import pytest
from eth.codecs import abi

from tests.evm_backends.base_env import ExecutionReverted
from vyper.compiler import compile_code
from vyper.exceptions import InstantiationException, StructureException, TypeMismatch


# call, but don't abi decode the output
def _call_no_decode(contract_method: Any, *args, **kwargs) -> bytes:
    contract = contract_method.contract
    calldata = contract_method.prepare_calldata(*args, **kwargs)
    output = contract.env.message_call(contract.address, data=calldata)

    return output


def test_buffer(get_contract, tx_failed):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> ReturnBuffer[100]:
    return convert(x, ReturnBuffer[100])
    """

    c = get_contract(test_bytes)
    return_data = b"cow"
    moo_result = _call_no_decode(c.foo, return_data)
    assert moo_result == return_data


def test_buffer_in_interface(get_contract, tx_failed):
    caller_code = """
interface Foo:
    def foo() -> ReturnBuffer[100]: view

@external
def foo(target: Foo) -> ReturnBuffer[100]:
    return staticcall target.foo()
    """

    return_data = abi.encode("(bytes)", (b"cow",))
    target_code = f"""
@external
def foo() -> ReturnBuffer[100]:
    return convert(x"{return_data.hex()}", ReturnBuffer[100])
    """
    caller = get_contract(caller_code)
    target = get_contract(target_code)

    assert _call_no_decode(caller.foo, target.address) == return_data


def test_buffer_str_convert(get_contract):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> ReturnBuffer[100]:
    return convert(convert(x, String[100]), ReturnBuffer[100])
    """

    c = get_contract(test_bytes)
    moo_result = _call_no_decode(c.foo, b"cow")
    assert moo_result == b"cow"


def test_buffer_returndatasize_check(get_contract):
    test_bytes = """
interface Foo:
    def payload() -> ReturnBuffer[127]: view

interface FooSanity:
    def payload() -> ReturnBuffer[128]: view

payload: public(Bytes[33])

@external
def set_payload(b: Bytes[33]):
    self.payload =  b

@external
def bar() -> ReturnBuffer[127]:
    return staticcall Foo(self).payload()

@external
def sanity_check() -> ReturnBuffer[128]:
    b: ReturnBuffer[128] = staticcall FooSanity(self).payload()
    return b
    """

    c = get_contract(test_bytes)
    payload = b"a" * 33
    c.set_payload(payload)
    assert c.payload() == payload

    res = _call_no_decode(c.sanity_check)

    assert len(res) == 128
    assert abi.decode("(bytes)", res) == (payload,)

    # revert due to returndatasize being too big
    with pytest.raises(ExecutionReverted):
        _call_no_decode(c.bar)


def test_buffer_no_subscriptable(get_contract, tx_failed):
    code = """
@external
def foo(x: Bytes[128]) -> bytes8:
    return convert(x, ReturnBuffer[128])[0]
    """

    with pytest.raises(StructureException, match="Not an indexable type"):
        compile_code(code)


def test_proxy_raw_return(get_contract):
    impl1 = """
@external
def foo() -> String[32]:
    return "Hello"
    """

    impl2 = """
@external
def foo() -> Bytes[32]:
    return b"Goodbye"
    """

    impl3 = """
@external
def foo() -> DynArray[uint256, 2]:
    #return [1, 2]
    a: DynArray[uint256, 2] = [1, 2]
    return a
    """

    proxy = """
target: address
@external
def set_implementation(target: address):
    self.target = target

@external
def foo() -> ReturnBuffer[128]:
    data: Bytes[128] = raw_call(self.target, msg.data, is_delegate_call=True, max_outsize=128)
    return convert(data, ReturnBuffer[128])
    """

    impl_c1 = get_contract(impl1)
    impl_c2 = get_contract(impl2)
    impl_c3 = get_contract(impl3)

    proxy_c = get_contract(proxy)

    proxy_c.set_implementation(impl_c1.address)
    res = _call_no_decode(proxy_c.foo)
    assert abi.decode("(bytes)", res) == (b"Hello",)

    proxy_c.set_implementation(impl_c2.address)
    res = _call_no_decode(proxy_c.foo)
    assert abi.decode("(string)", res) == ("Goodbye",)

    proxy_c.set_implementation(impl_c3.address)
    res = _call_no_decode(proxy_c.foo)
    assert abi.decode("(uint256[])", res) == ([1, 2],)


fail_list = [
    ("b: ReturnBuffer[128]", InstantiationException),
    (
        """b: immutable(ReturnBuffer[128])

@deploy
def __init__():
    helper: Bytes[128] = b''
    b = convert(helper, ReturnBuffer[128])
    """,
        InstantiationException,
    ),
    (
        "b: constant(ReturnBuffer[128]) = b''",
        TypeMismatch,
    ),  # type mismatch for now until we allow buffer literals
    ("b: transient(ReturnBuffer[128])", InstantiationException),
    ("b: DynArray[ReturnBuffer[128], 2]", StructureException),
    (
        """
@external
def foo(b: ReturnBuffer[128]):
    pass
    """,
        InstantiationException,
    ),
]


# TODO: move these to syntax tests
@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_abibuffer_fail(bad_code, exc):
    with pytest.raises(exc):
        compile_code(bad_code)
