from decimal import Decimal


def test_abi_decode(get_contract, abi_encode):
    contract = """
@external
def abi_decode_single(x: Bytes[32]) -> uint256:
    a: uint256 = 0
    a = _abi_decode(x, types=[uint256])
    return a

@external
def abi_decode(x: Bytes[64]) -> (address, int128):
    a: address = ZERO_ADDRESS
    b: int128 = 0
    a, b = _abi_decode(x, types=[address, int128])
    return a, b

@external
def abi_decode2(x: Bytes[64]) -> (uint256, uint256):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x, types=[uint256, uint256])
    return a, b

@external
def abi_decode3(x: Bytes[160]) -> String[5]:
    a: String[5] = ""
    a = _abi_decode(x, types=[String[5]])
    return a

@external
def abi_decode4(x: Bytes[192]) -> (String[5], address):
    a: String[5] = ""
    b: address = ZERO_ADDRESS
    a, b = _abi_decode(x, types=[String[5], address])
    return a, b
    """

    c = get_contract(contract)

    encoded = abi_encode("uint256", 123)
    assert c.abi_decode_single(encoded) == 123

    test_addr = b"".join(chr(i).encode("utf-8") for i in range(20))
    expected_test_addr = "0x" + test_addr.hex()
    encoded = abi_encode("(address,int128)", (test_addr, 123))

    assert tuple(c.abi_decode(encoded)) == (expected_test_addr, 123)

    arg1 = 123
    arg2 = 456
    assert tuple(c.abi_decode2(abi_encode("(uint256,uint256)", (arg1, arg2)))) == (123, 456)

    arg = "vyper"
    encoded = abi_encode("string", arg)
    assert c.abi_decode3(encoded) == "vyper"

    arg = ("vyper", test_addr)
    encoding = "(string,address)"
    encoded = abi_encode(encoding, arg)
    assert tuple(c.abi_decode4(encoded)) == ("vyper", expected_test_addr)
