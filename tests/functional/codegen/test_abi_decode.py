from decimal import Decimal

from vyper.exceptions import StructureException


def test_abi_decode(get_contract, abi_encode):
    contract = """
@external
def abi_decode_single(x: Bytes[32]) -> uint256:
    a: uint256 = 0
    a = _abi_decode(x, types=[uint256])
    return a

@external
def abi_decode_single_2(x: Bytes[64]) -> String[5]:
    a: String[5] = ""
    a = _abi_decode(x, types=[String[5]])
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
def abi_decode3(x: Bytes[160]) -> (address, int128, bool, decimal, bytes32):
    a: address = ZERO_ADDRESS
    b: int128 = 0
    c: bool = False
    d: decimal = 0.0
    e: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000000
    a, b, c, d, e = _abi_decode(x, types=[address, int128, bool, decimal, bytes32])
    return a, b, c, d, e

@external
def abi_decode4(x: Bytes[128]) -> (String[5], address):
    a: String[5] = ""
    b: address = ZERO_ADDRESS
    a, b = _abi_decode(x, types=[String[5], address])
    return a, b
    """

    c = get_contract(contract)

    encoded = abi_encode("uint256", 123)
    assert c.abi_decode_single(encoded) == 123

    arg = "vyper"
    encoded = abi_encode("string", arg)
    assert c.abi_decode_single_2(encoded) == "vyper"

    test_addr = b"".join(chr(i).encode("utf-8") for i in range(20))
    expected_test_addr = "0x" + test_addr.hex()
    encoded = abi_encode("(address,int128)", (test_addr, 123))

    assert tuple(c.abi_decode(encoded)) == (expected_test_addr, 123)

    arg1 = 123
    arg2 = 456
    assert tuple(c.abi_decode2(abi_encode("(uint256,uint256)", (arg1, arg2)))) == (123, 456)

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    args = (test_addr, -1, True, Decimal("-123.4"), test_bytes32)
    encoding = "(address,int128,bool,fixed168x10,bytes32)"
    encoded = abi_encode(encoding, args)
    assert tuple(c.abi_decode3(encoded)) == (
        expected_test_addr,
        -1,
        True,
        Decimal("-123.4"),
        test_bytes32,
    )

    arg = ("vyper", test_addr)
    encoding = "(string,address)"
    encoded = abi_encode(encoding, arg)
    assert tuple(c.abi_decode4(encoded)) == ("vyper", expected_test_addr)


def test_abi_decode_length_mismatch(get_contract, assert_compile_failed):
    contract = """
@external
def foo(x: Bytes[32]):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x, types=[uint256, uint256])
    """
    assert_compile_failed(lambda: get_contract(contract), StructureException)


def test_abi_decode_array(get_contract, abi_encode):
    contract = """
@external
def abi_decode(x: Bytes[96]) -> uint256[3]:
    a: uint256[3] = [0, 0, 0]
    a = _abi_decode(x, types=[uint256[3]])
    return a
    """

    c = get_contract(contract)

    arg = [123, 456, 789]
    assert c.abi_decode(abi_encode("uint256[3]", arg)) == arg


def test_abi_decode_dynarray(get_contract, abi_encode):
    contract = """
@external
def abi_decode(x: Bytes[160]) -> DynArray[uint256, 3]:
    a: DynArray[uint256, 3] = [0, 0, 0]
    a = _abi_decode(x, types=[DynArray[uint256, 3]])
    return a
    """

    c = get_contract(contract, skip_grammar=True)

    arg = [123, 456, 789]
    assert c.abi_decode(abi_encode("uint256[]", arg)) == arg
