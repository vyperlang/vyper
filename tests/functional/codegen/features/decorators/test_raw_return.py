from eth.codecs import abi


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
def greet() -> String[32]:
    return "Hello"
    """

    impl2 = """
# test delegate calling with a different type, but byte-compatible in abi
@external
def greet() -> Bytes[32]:
    return b"Goodbye"
    """

    proxy = """
target: address

@external
def set_implementation(target: address):
    self.target = target

@external
@raw_return
def greet() -> Bytes[128]:
    # forward msg.data to the implementation contract
    data: Bytes[128] = raw_call(self.target, msg.data, is_delegate_call=True, max_outsize=128)
    return data
    """

    impl_c1 = get_contract(impl1)
    impl_c2 = get_contract(impl2)

    proxy_c = get_contract(proxy)

    proxy_c.set_implementation(impl_c1.address)
    assert proxy_c.greet() == b"Hello"
    assert impl_c1.greet() == "Hello"  # different type

    proxy_c.set_implementation(impl_c2.address)
    assert impl_c2.greet() == b"Goodbye"
    assert proxy_c.greet() == b"Goodbye"  # identical
