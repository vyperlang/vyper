import pytest
from eth.codecs import abi

from vyper.compiler import compile_code
from vyper.exceptions import InstantiationException, StructureException, TypeMismatch
from vyper.utils import method_id


def test_buffer(get_contract, tx_failed):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> ReturnBuffer[100]:
    return convert(x, ReturnBuffer[100])
    """

    c = get_contract(test_bytes)
    moo_result = c.foo(abi.encode("(bytes)", (b"cow",)))
    assert moo_result == b"cow"


def test_buffer_in_interface(get_contract, tx_failed):
    caller_code = """
interface Foo:
    def foo() -> ReturnBuffer[100]: view

@external
def foo(target: Foo) -> ReturnBuffer[100]:
    return staticcall target.foo()
    """

    return_data = abi.encode("(bytes)", (b"cow",)).hex()
    target_code = f"""
@external
def foo() -> ReturnBuffer[100]:
    return convert(x"{return_data}", ReturnBuffer[100])
    """
    caller = get_contract(caller_code)
    target = get_contract(target_code)

    assert caller.foo(target.address) == b"cow"


def test_buffer_str_convert(get_contract):
    test_bytes = """
@external
def foo(x: Bytes[100]) -> ReturnBuffer[100]:
    return convert(convert(x, String[100]), ReturnBuffer[100])
    """

    c = get_contract(test_bytes)
    moo_result = c.foo(abi.encode("(bytes)", (b"cow",)))
    assert moo_result == b"cow"


def test_buffer_no_subscriptable(get_contract, tx_failed):
    code = """
@external
def foo(x: Bytes[128]) -> bytes8:
    return convert(x, ReturnBuffer[128])[0]
    """

    with pytest.raises(StructureException, match="Not an indexable type"):
        compile_code(code)


def test_proxy_raw_return(env, get_contract):
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
    assert proxy_c.foo() == b"Hello"

    proxy_c.set_implementation(impl_c2.address)
    assert proxy_c.foo() == b"Goodbye"

    proxy_c.set_implementation(impl_c3.address)
    # need low-level call otherwise we fail due to bytes decoding
    # because ABIBytes is represented as bytes in ABI
    res = env.message_call(proxy_c.address, data=method_id("foo()"))
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
    ("b: DynArray[ReturnBuffer[128], 2]", InstantiationException),
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
