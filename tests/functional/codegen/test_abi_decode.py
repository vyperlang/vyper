def test_abi_decode(get_contract, abi_encode):
    contract = """
@external
def abi_decode(x: Bytes[64]) -> (uint256, uint256):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x, types=[uint256, uint256])
    return a, b
    """

    c = get_contract(contract)

    arg1 = 123
    arg2 = 456
    assert tuple(c.abi_decode(abi_encode("(uint256,uint256)", (arg1, arg2)))) == (123, 456)
