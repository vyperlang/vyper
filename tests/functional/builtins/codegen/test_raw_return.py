from eth.codecs import abi


def test_raw_return(env, get_contract):
    code = """
@external
def foo(data: Bytes[128]) -> DynArray[uint256, 2]:
    raw_return(data)
    """

    c = get_contract(code)

    data = [1, 2]
    abi_encoded = abi.encode("(uint256[])", (data,))
    assert c.foo(abi_encoded) == data


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
def greet() -> String[32]:
    # forward msg.data to the implementation contract
    data: Bytes[128] = raw_call(self.target, msg.data, is_delegate_call=True, max_outsize=128)
    raw_return(data)
    """

    impl_c1 = get_contract(impl1)
    impl_c2 = get_contract(impl2)

    proxy_c = get_contract(proxy)

    proxy_c.set_implementation(impl_c1.address)
    assert proxy_c.greet() == impl_c1.greet() == "Hello"

    proxy_c.set_implementation(impl_c2.address)
    assert impl_c2.greet() == b"Goodbye"
    assert proxy_c.greet() == "Goodbye"  # note: unsafe casted from bytes
