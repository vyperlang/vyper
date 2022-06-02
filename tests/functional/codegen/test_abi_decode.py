from decimal import Decimal

import pytest

from vyper.exceptions import StructureException


def test_abi_decode(get_contract, abi_encode):
    contract = """
struct Animal:
  name: String[5]
  address_: address
  id_: int128
  is_furry: bool
  price: decimal
  data: uint256[3]
  metadata: bytes32

struct Human:
  name: String[64]
  pet: Animal

@external
def abi_decode_single(x: Bytes[32]) -> uint256:
    a: uint256 = 0
    a = _abi_decode(x)
    return a

@external
def abi_decode_single_2(x: Bytes[64]) -> String[5]:
    a: String[5] = ""
    a = _abi_decode(x)
    return a

@external
def abi_decode(x: Bytes[64]) -> (address, int128):
    a: address = ZERO_ADDRESS
    b: int128 = 0
    a, b = _abi_decode(x)
    return a, b

@external
def abi_decode2(x: Bytes[64]) -> (uint256, uint256):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x)
    return a, b

@external
def abi_decode3(x: Bytes[160]) -> (address, int128, bool, decimal, bytes32):
    a: address = ZERO_ADDRESS
    b: int128 = 0
    c: bool = False
    d: decimal = 0.0
    e: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000000
    a, b, c, d, e = _abi_decode(x)
    return a, b, c, d, e

@external
def abi_decode4(x: Bytes[128]) -> (String[5], address):
    a: String[5] = ""
    b: address = ZERO_ADDRESS
    a, b = _abi_decode(x)
    return a, b

@external
def abi_decode_struct(x: Bytes[544]) -> Human:
    human: Human = Human({
        name: "",
        pet: Animal({
            name: "",
            address_: ZERO_ADDRESS,
            id_: 0,
            is_furry: False,
            price: 0.0,
            data: [0, 0, 0],
            metadata: 0x0000000000000000000000000000000000000000000000000000000000000000
        })
    })
    human = _abi_decode(x)
    return human
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

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    human_tuple = (
        "foobar",
        ("vyper", test_addr, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )
    args = tuple([human_tuple[0]] + list(human_tuple[1]))
    human_t = "(string,(string,address,int128,bool,fixed168x10,uint256[3],bytes32))"
    human_encoded = abi_encode(human_t, human_tuple)
    assert tuple(c.abi_decode_struct(human_encoded)) == (
        "foobar",
        ("vyper", expected_test_addr, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )


def test_abi_decode_length_mismatch(get_contract, assert_compile_failed):
    contract = """
@external
def foo(x: Bytes[32]):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x)
    """
    assert_compile_failed(lambda: get_contract(contract), StructureException)


@pytest.mark.parametrize(
    "type,abi_type,size",
    [("uint256[3]", "uint256[3]", 96), ("DynArray[uint256, 3]", "uint256[]", 160)],
)
def test_abi_decode_array(get_contract, abi_encode, type, abi_type, size):
    contract = f"""
@external
def abi_decode(x: Bytes[{size}]) -> {type}:
    a: {type} = [0, 0, 0]
    a = _abi_decode(x)
    return a
    """

    c = get_contract(contract)

    arg = [123, 456, 789]
    assert c.abi_decode(abi_encode(abi_type, arg)) == arg


@pytest.mark.parametrize(
    "type,abi_type,size",
    [("uint256[3]", "uint256[3]", 128), ("DynArray[uint256, 3]", "uint256[]", 192)],
)
def test_abi_decode_array2(get_contract, abi_encode, type, abi_type, size):
    contract = f"""
@external
def abi_decode(x: Bytes[{size}]) -> ({type}, bool):
    a: {type} = [0, 0, 0]
    b: bool = False
    a, b = _abi_decode(x)
    return a, b
    """

    c = get_contract(contract)

    arg = ([123, 456, 789], True)
    assert tuple(c.abi_decode(abi_encode(f"({abi_type},bool)", arg))) == arg


nested_2d_array_args = [
    [[123, 456, 789], [234, 567, 891], [345, 678, 912]],
    [[], [], []],
    [[123, 456], [234, 567, 891]],
    [[123, 456, 789], [234, 567], [345]],
    [[123], [], [345, 678, 912]],
    [[], [], [345, 678, 912]],
    [[], [], [345]],
    [[], [234], []],
    [[], [234, 567, 891], []],
    [[]],
    [[123], [234]],
]


@pytest.mark.parametrize("args", nested_2d_array_args)
def test_abi_decode_nested_dynarray(get_contract, abi_encode, args):
    code = """
@external
def abi_decode(x: Bytes[544]) -> DynArray[DynArray[uint256, 3], 3]:
    a: DynArray[DynArray[uint256, 3], 3] = []
    a = _abi_decode(x)
    return a
    """

    c = get_contract(code)

    encoded = abi_encode("uint256[][]", args)
    assert c.abi_decode(encoded) == args


nested_3d_array_args = [
    [
        [[123, 456, 789], [234, 567, 891], [345, 678, 912]],
        [[234, 567, 891], [345, 678, 912], [123, 456, 789]],
        [[345, 678, 912], [123, 456, 789], [234, 567, 891]],
    ],
    [
        [[123, 789], [234], [345, 678, 912]],
        [[234, 567], [345, 678]],
        [[345]],
    ],
    [
        [[123], [234, 567, 891]],
        [[234]],
    ],
    [
        [[], [], []],
        [[], [], []],
        [[], [], []],
    ],
    [
        [[123, 456, 789], [234, 567, 891], [345, 678, 912]],
        [[234, 567, 891], [345, 678, 912]],
        [[]],
    ],
    [
        [[]],
        [[]],
        [[234]],
    ],
    [
        [[123]],
        [[]],
        [[]],
    ],
    [
        [[]],
        [[123]],
        [[]],
    ],
    [
        [[123, 456, 789], [234, 567]],
        [[234]],
        [[567], [912], [345]],
    ],
    [
        [[]],
    ],
]


@pytest.mark.parametrize("args", nested_3d_array_args)
def test_abi_decode_nested_dynarray2(get_contract, abi_encode, args):
    code = """
@external
def abi_decode(x: Bytes[1700]) -> DynArray[DynArray[DynArray[uint256, 3], 3], 3]:
    a: DynArray[DynArray[DynArray[uint256, 3], 3], 3] = []
    a = _abi_decode(x)
    return a
    """

    c = get_contract(code)

    encoded = abi_encode("uint256[][][]", args)
    assert c.abi_decode(encoded) == args


def test_side_effects_evaluation(get_contract, abi_encode):
    contract_1 = """
counter: uint256

@external
def __init__():
    self.counter = 0

@external
def get_counter() -> Bytes[160]:
    self.counter += 1
    return _abi_encode(self.counter, "hello")
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def get_counter() -> Bytes[160]: nonpayable

@external
def foo(addr: address) -> (uint256, String[6]):
    return _abi_decode(Foo(addr).get_counter())
    """

    c2 = get_contract(contract_2)

    assert tuple(c2.foo(c.address)) == (1, "hello")


def test_abi_decode_private_dynarray(get_contract, abi_encode):
    code = """
bytez: DynArray[uint256, 3]

@internal
def _foo(bs: Bytes[160]):
    self.bytez = _abi_decode(bs)

@external
def foo(bs: Bytes[160]) -> (uint256, DynArray[uint256, 3]):
    dont_clobber_me: uint256 = MAX_UINT256
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = [1, 2, 3]
    encoded = abi_encode("uint256[]", bs)
    assert c.foo(encoded) == [2 ** 256 - 1, bs]


def test_abi_decode_private_nested_dynarray(get_contract, abi_encode):
    code = """
bytez: DynArray[DynArray[DynArray[uint256, 3], 3], 3]

@internal
def _foo(bs: Bytes[1696]):
    self.bytez = _abi_decode(bs)

@external
def foo(bs: Bytes[1696]) -> (uint256, DynArray[DynArray[DynArray[uint256, 3], 3], 3]):
    dont_clobber_me: uint256 = MAX_UINT256
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = [
        [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        [[10, 11, 12], [13, 14, 15], [16, 17, 18]],
        [[19, 20, 21], [22, 23, 24], [25, 26, 27]],
    ]
    encoded = abi_encode("uint256[][][]", bs)
    assert c.foo(encoded) == [2 ** 256 - 1, bs]


def test_abi_decode_return(get_contract, abi_encode):
    contract = """
@external
def abi_decode(x: Bytes[64]) -> (address, int128):
    return _abi_decode(x)
    """

    c = get_contract(contract)

    test_addr = b"".join(chr(i).encode("utf-8") for i in range(20))
    expected_test_addr = "0x" + test_addr.hex()
    encoded = abi_encode("(address,int128)", (test_addr, 123))

    assert tuple(c.abi_decode(encoded)) == (expected_test_addr, 123)
