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
