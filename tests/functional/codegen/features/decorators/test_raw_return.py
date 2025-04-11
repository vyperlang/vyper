from eth.codecs import abi

from vyper.utils import method_id


def test_raw_return(get_contract, tx_failed):
    test_bytes = """
@external
@raw_return
def foo(x: Bytes[100]) -> Bytes[100]:
    return x
    """

    c = get_contract(test_bytes)
    moo_result = c.foo(abi.encode("(bytes)", (b"cow",)))
    assert moo_result == b"cow"


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
@raw_return
def foo() -> Bytes[128]:
    data: Bytes[128] = raw_call(
        self.target,
        msg.data,
        is_delegate_call=True,
        max_outsize=128
    )
    return data
    """

    impl_c1 = get_contract(impl1)
    impl_c2 = get_contract(impl2)
    impl_c3 = get_contract(impl3)

    proxy_c = get_contract(proxy)

    assert impl_c1.foo() == "Hello"
    proxy_c.set_implementation(impl_c1.address)
    assert proxy_c.foo() == b"Hello"

    assert impl_c2.foo() == b"Goodbye"
    proxy_c.set_implementation(impl_c2.address)
    assert proxy_c.foo() == b"Goodbye"

    assert impl_c3.foo() == [1, 2]
    proxy_c.set_implementation(impl_c3.address)
    # need low-level call otherwise we fail due to bytes decoding
    # because ABIBytes is represented as bytes in ABI
    res = env.message_call(proxy_c.address, data=method_id("foo()"))
    assert abi.decode("(uint256[])", res) == ([1, 2],)
