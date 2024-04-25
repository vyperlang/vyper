from decimal import Decimal

import pytest
from eth.codecs import abi

from vyper.exceptions import ArgumentException, StackTooDeep, StructureException
from vyper.utils import method_id

TEST_ADDR = "0x" + b"".join(chr(i).encode("utf-8") for i in range(20)).hex()


def test_abi_decode_complex(get_contract):
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
def abi_decode(x: Bytes[160]) -> (address, int128, bool, decimal, bytes32):
    a: address = empty(address)
    b: int128 = 0
    c: bool = False
    d: decimal = 0.0
    e: bytes32 = 0x0000000000000000000000000000000000000000000000000000000000000000
    a, b, c, d, e = _abi_decode(x, (address, int128, bool, decimal, bytes32))
    return a, b, c, d, e

@external
def abi_decode_struct(x: Bytes[544]) -> Human:
    human: Human = Human(
        name="",
        pet=Animal(
            name="",
            address_=empty(address),
            id_=0,
            is_furry=False,
            price=0.0,
            data=[0, 0, 0],
            metadata=0x0000000000000000000000000000000000000000000000000000000000000000
        )
    )
    human = _abi_decode(x, Human)
    return human
    """

    c = get_contract(contract)

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    args = (TEST_ADDR, -1, True, Decimal("-123.4"), test_bytes32)
    encoding = "(address,int128,bool,fixed168x10,bytes32)"
    encoded = abi.encode(encoding, args)
    assert tuple(c.abi_decode(encoded)) == (TEST_ADDR, -1, True, Decimal("-123.4"), test_bytes32)

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    human_tuple = (
        "foobar",
        ("vyper", TEST_ADDR, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )
    args = tuple([human_tuple[0]] + list(human_tuple[1]))
    human_t = "((string,(string,address,int128,bool,fixed168x10,uint256[3],bytes32)))"
    human_encoded = abi.encode(human_t, (human_tuple,))
    assert tuple(c.abi_decode_struct(human_encoded)) == (
        "foobar",
        ("vyper", TEST_ADDR, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )


@pytest.mark.parametrize(
    "expected,input_len,output_typ,abi_typ,unwrap_tuple",
    [
        (123, 32, "uint256", "uint256", False),
        (123, 32, "uint256", "(uint256)", True),
        ("vyper", 64, "String[5]", "string", False),
        ("vyper", 96, "String[5]", "(string)", True),
        ([123, 456, 789], 96, "uint256[3]", "uint256[3]", False),
        ([123, 456, 789], 96, "uint256[3]", "(uint256[3])", True),
        ([123, 456, 789], 128, "DynArray[uint256, 3]", "uint256[]", False),
        ([123, 456, 789], 160, "DynArray[uint256, 3]", "(uint256[])", True),
    ],
)
def test_abi_decode_single(
    w3, get_contract, expected, input_len, output_typ, abi_typ, unwrap_tuple
):
    contract = f"""
@external
def foo(x: Bytes[{input_len}]) -> {output_typ}:
    a: {output_typ} = _abi_decode(x, {output_typ}, unwrap_tuple={unwrap_tuple})
    return a
    """
    c = get_contract(contract)

    encode_arg = expected
    if unwrap_tuple is True:
        encode_arg = (expected,)

    encoded = abi.encode(abi_typ, encode_arg)
    assert c.foo(encoded) == expected


@pytest.mark.parametrize(
    "arg,expected,input_len,output_typ1,output_typ2,abi_typ",
    [
        ((123, 456), (123, 456), 64, "uint256", "uint256", "(uint256,uint256)"),
        ((TEST_ADDR, 123), (TEST_ADDR, 123), 64, "address", "int128", "(address,int128)"),
        (
            ("vyper", TEST_ADDR),
            ("vyper", TEST_ADDR),
            128,
            "String[5]",
            "address",
            "(string,address)",
        ),
        ((1, b"234"), (1, b"234"), 128, "uint256", "Bytes[32]", ("(uint256,bytes)")),
    ],
)
@pytest.mark.parametrize("unwrap_tuple", (True, False))
def test_abi_decode_double(
    get_contract, arg, expected, input_len, output_typ1, output_typ2, abi_typ, unwrap_tuple
):
    contract = f"""
@external
def foo(x: Bytes[{input_len}]) -> ({output_typ1}, {output_typ2}):
    a: {output_typ1} = empty({output_typ1})
    b: {output_typ2} = empty({output_typ2})
    a, b = _abi_decode(x, ({output_typ1}, {output_typ2}), unwrap_tuple={unwrap_tuple})
    return a, b
    """

    c = get_contract(contract)
    encoded = abi.encode(abi_typ, arg)
    assert tuple(c.foo(encoded)) == expected


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
@pytest.mark.parametrize("unwrap_tuple", (True, False))
def test_abi_decode_nested_dynarray(get_contract, args, unwrap_tuple):
    if unwrap_tuple is True:
        encoded = abi.encode("(uint256[][])", (args,))
        len = 544
    else:
        encoded = abi.encode("uint256[][]", args)
        len = 512

    code = f"""
@external
def abi_decode(x: Bytes[{len}]) -> DynArray[DynArray[uint256, 3], 3]:
    a: DynArray[DynArray[uint256, 3], 3] = []
    a = _abi_decode(x, DynArray[DynArray[uint256, 3], 3], unwrap_tuple={unwrap_tuple})
    return a
    """

    c = get_contract(code)
    assert c.abi_decode(encoded) == args


nested_3d_array_args = [
    [
        [[123, 456, 789], [234, 567, 891], [345, 678, 912]],
        [[234, 567, 891], [345, 678, 912], [123, 456, 789]],
        [[345, 678, 912], [123, 456, 789], [234, 567, 891]],
    ],
    [[[123, 789], [234], [345, 678, 912]], [[234, 567], [345, 678]], [[345]]],
    [[[123], [234, 567, 891]], [[234]]],
    [[[], [], []], [[], [], []], [[], [], []]],
    [[[123, 456, 789], [234, 567, 891], [345, 678, 912]], [[234, 567, 891], [345, 678, 912]], [[]]],
    [[[]], [[]], [[234]]],
    [[[123]], [[]], [[]]],
    [[[]], [[123]], [[]]],
    [[[123, 456, 789], [234, 567]], [[234]], [[567], [912], [345]]],
    [[[]]],
]


@pytest.mark.parametrize("args", nested_3d_array_args)
@pytest.mark.parametrize("unwrap_tuple", (True, False))
@pytest.mark.venom_xfail(raises=StackTooDeep, reason="stack scheduler regression")
def test_abi_decode_nested_dynarray2(get_contract, args, unwrap_tuple):
    if unwrap_tuple is True:
        encoded = abi.encode("(uint256[][][])", (args,))
        len = 1696
    else:
        encoded = abi.encode("uint256[][][]", args)
        len = 1664

    code = f"""
@external
def abi_decode(x: Bytes[{len}]) -> DynArray[DynArray[DynArray[uint256, 3], 3], 3]:
    a: DynArray[DynArray[DynArray[uint256, 3], 3], 3] = []
    a = _abi_decode(
        x,
        DynArray[DynArray[DynArray[uint256, 3], 3], 3],
        unwrap_tuple={unwrap_tuple}
    )
    return a
    """

    c = get_contract(code)
    assert c.abi_decode(encoded) == args


def test_side_effects_evaluation(get_contract):
    contract_1 = """
counter: uint256

@deploy
def __init__():
    self.counter = 0

@external
def get_counter() -> Bytes[128]:
    self.counter += 1
    return _abi_encode(self.counter, "hello")
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def get_counter() -> Bytes[128]: nonpayable

@external
def foo(addr: address) -> (uint256, String[5]):
    a: uint256 = 0
    b: String[5] = ""
    a, b = _abi_decode(extcall Foo(addr).get_counter(), (uint256, String[5]), unwrap_tuple=False)
    return a, b
    """

    c2 = get_contract(contract_2)

    assert tuple(c2.foo(c.address)) == (1, "hello")


def test_abi_decode_private_dynarray(get_contract):
    code = """
bytez: DynArray[uint256, 3]

@internal
def _foo(bs: Bytes[160]):
    self.bytez = _abi_decode(bs, DynArray[uint256, 3])

@external
def foo(bs: Bytes[160]) -> (uint256, DynArray[uint256, 3]):
    dont_clobber_me: uint256 = max_value(uint256)
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = [1, 2, 3]
    encoded = abi.encode("(uint256[])", (bs,))
    assert c.foo(encoded) == [2**256 - 1, bs]


@pytest.mark.venom_xfail(raises=StackTooDeep, reason="stack scheduler regression")
def test_abi_decode_private_nested_dynarray(get_contract):
    code = """
bytez: DynArray[DynArray[DynArray[uint256, 3], 3], 3]

@internal
def _foo(bs: Bytes[1696]):
    self.bytez = _abi_decode(bs, DynArray[DynArray[DynArray[uint256, 3], 3], 3])

@external
def foo(bs: Bytes[1696]) -> (uint256, DynArray[DynArray[DynArray[uint256, 3], 3], 3]):
    dont_clobber_me: uint256 = max_value(uint256)
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = [
        [[1, 2, 3], [4, 5, 6], [7, 8, 9]],
        [[10, 11, 12], [13, 14, 15], [16, 17, 18]],
        [[19, 20, 21], [22, 23, 24], [25, 26, 27]],
    ]
    encoded = abi.encode("(uint256[][][])", (bs,))
    assert c.foo(encoded) == [2**256 - 1, bs]


def test_abi_decode_return(get_contract):
    contract = """
@external
def abi_decode(x: Bytes[64]) -> (address, int128):
    return _abi_decode(x, (address, int128))
    """

    c = get_contract(contract)

    encoded = abi.encode("(address,int128)", (TEST_ADDR, 123))

    assert tuple(c.abi_decode(encoded)) == (TEST_ADDR, 123)


def test_abi_decode_annassign(get_contract):
    contract = """
@external
def abi_decode(x: Bytes[32]) -> uint256:
    a: uint256 = _abi_decode(x, uint256, unwrap_tuple=False)
    return a
    """
    c = get_contract(contract)

    encoded = abi.encode("uint256", 123)
    assert c.abi_decode(encoded) == 123


@pytest.mark.parametrize(
    "input_",
    [
        b"",  # Length of byte array is below minimum size of output type
        b"\x01" * 96,  # Length of byte array is beyond size bound of output type
    ],
)
def test_clamper(get_contract, tx_failed, input_):
    contract = """
@external
def abi_decode(x: Bytes[96]) -> (uint256, uint256):
    a: uint256 = empty(uint256)
    b: uint256 = empty(uint256)
    a, b = _abi_decode(x, (uint256, uint256))
    return a, b
    """
    c = get_contract(contract)
    with tx_failed():
        c.abi_decode(input_)


def test_clamper_nested_uint8(get_contract, tx_failed):
    # check that _abi_decode clamps on word-types even when it is in a nested expression
    # decode -> validate uint8 -> revert if input >= 256 -> cast back to uint256
    contract = """
@external
def abi_decode(x: uint256) -> uint256:
    a: uint256 = convert(_abi_decode(slice(msg.data, 4, 32), (uint8)), uint256)
    return a
    """
    c = get_contract(contract)
    assert c.abi_decode(255) == 255
    with tx_failed():
        c.abi_decode(256)


def test_clamper_nested_bytes(get_contract, tx_failed):
    # check that _abi_decode clamps dynamic even when it is in a nested expression
    # decode -> validate Bytes[20] -> revert if len(input) > 20 -> convert back to -> add 1
    contract = """
@external
def abi_decode(x: Bytes[96]) -> Bytes[21]:
    a: Bytes[21] = concat(b"a", _abi_decode(x, Bytes[20]))
    return a
    """
    c = get_contract(contract)
    assert c.abi_decode(abi.encode("(bytes)", (b"bc",))) == b"abc"
    with tx_failed():
        c.abi_decode(abi.encode("(bytes)", (b"a" * 22,)))


@pytest.mark.parametrize(
    "output_typ,input_",
    [
        ("DynArray[uint256, 3]", b""),
        ("DynArray[uint256, 3]", b"\x01" * 192),
        ("Bytes[5]", b""),
        ("Bytes[5]", b"\x01" * 192),
    ],
)
def test_clamper_dynamic(get_contract, tx_failed, output_typ, input_):
    contract = f"""
@external
def abi_decode(x: Bytes[192]) -> {output_typ}:
    a: {output_typ} = empty({output_typ})
    a = _abi_decode(x, {output_typ})
    return a
    """
    c = get_contract(contract)
    with tx_failed():
        c.abi_decode(input_)


@pytest.mark.parametrize(
    "arg,encoding,expected", [(123, "(uint256)", 123), ([123, 456, 789], "(uint256[])", 789)]
)
def test_abi_decode_conditional(get_contract, arg, encoding, expected):
    contract = """
@external
def abi_decode(x: Bytes[160]) -> uint256:
    if len(x) == 32:
        a: uint256 = _abi_decode(x, uint256)
        return a
    elif len(x) == 160:
        b: DynArray[uint256, 3] = _abi_decode(x, DynArray[uint256, 3])
        return b[2]
    return 0
    """
    c = get_contract(contract)
    encoded = abi.encode(encoding, (arg,))
    assert c.abi_decode(encoded) == expected


@pytest.mark.parametrize(
    "output_typ1,output_typ2,input_",
    [
        ("DynArray[uint256, 3]", "uint256", b""),
        ("DynArray[uint256, 3]", "uint256", b"\x01" * 128),
        ("Bytes[5]", "address", b""),
        ("Bytes[5]", "address", b"\x01" * 128),
    ],
)
def test_clamper_dynamic_tuple(get_contract, tx_failed, output_typ1, output_typ2, input_):
    contract = f"""
@external
def abi_decode(x: Bytes[224]) -> ({output_typ1}, {output_typ2}):
    a: {output_typ1} = empty({output_typ1})
    b: {output_typ2} = empty({output_typ2})
    a, b = _abi_decode(x, ({output_typ1}, {output_typ2}))
    return a, b
    """
    c = get_contract(contract)
    with tx_failed():
        c.abi_decode(input_)


FAIL_LIST = [
    (
        """
@external
def foo(x: Bytes[32]):
    a: uint256 = 0
    b: uint256 = 0
    a, b = _abi_decode(x, (uint256, uint256))
    """,
        StructureException,  # Size of input data is smaller than expected output
    ),
    (
        """
@external
def foo(x: Bytes[32]):
    _abi_decode(x)
    """,
        ArgumentException,  # Output types arg is missing
    ),
]


@pytest.mark.parametrize("bad_code,exception", FAIL_LIST)
def test_abi_decode_length_mismatch(get_contract, assert_compile_failed, bad_code, exception):
    assert_compile_failed(lambda: get_contract(bad_code), exception)


def test_abi_decode_arithmetic_overflow(w3, tx_failed, get_contract):
    # test based on GHSA-9p8r-4xp4-gw5w:
    # https://github.com/vyperlang/vyper/security/advisories/GHSA-9p8r-4xp4-gw5w#advisory-comment-91841
    # note: doesn't even reach the assert but reverts internally on the clamp in getelemptr
    code = """
@external
def f(x: Bytes[32 * 3]):
    a: Bytes[32] = b"foo"
    y: Bytes[32 * 3] = x

    decoded_y1: Bytes[32] = _abi_decode(y, Bytes[32])
    a = b"bar"
    decoded_y2: Bytes[32] = _abi_decode(y, Bytes[32])

    assert decoded_y1 != decoded_y2
    """
    c = get_contract(code)
    data = method_id("f(bytes)")
    data += (0x20).to_bytes(32, "big")  # tuple head
    data += (0x60).to_bytes(32, "big")  # parent array length
    # parent payload - this word will be considered as the head of the abi-encoded inner array
    # and it will be added to base ptr leading to an arithmetic overflow
    data += (2**256 - 0x60).to_bytes(32, "big")
    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "data": data})


def test_abi_decode_oob_due_to_invalid_head(w3, tx_failed, get_contract):
    code = """
@external
def f(x: Bytes[32 * 5]):
    y: Bytes[32 * 5] = x
    a: Bytes[32] = b"a"
    decoded_y1: DynArray[uint256, 3] = _abi_decode(y, DynArray[uint256, 3])
    a = b"aaaa"
    decoded_y1 = _abi_decode(y, DynArray[uint256, 3])
    """
    c = get_contract(code)
    data = method_id("f(bytes)")
    data += (0x20).to_bytes(32, "big")  # tuple head
    data += (0xA0).to_bytes(32, "big")  # parent array length
    # head should be 20 and thus the decoding func would decode 1 byte
    # over the end of the input data
    # _getelemptr_abi_helper will revert due to clamping
    data += (0x21).to_bytes(32, "big")  # invalid inner array head (1 byte over)
    # we don't want to revert on invalid length, so set this to 0
    # the first byte of payload will be considered as the length
    data += (0x00).to_bytes(32, "big")
    data += (0x01).to_bytes(1, "big")  # will be considered as the length=1
    data += (0x00).to_bytes(31, "big")
    data += (0x03).to_bytes(32, "big") * 2
    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "data": data})


def test_abi_decode_oob_due_to_invalid_head2(w3, tx_failed, get_contract):
    code = """
@external
def run(x: Bytes[2 * 32 + 3 * 32  + 3 * 32 * 4]):
    y: Bytes[2 * 32 + 3 * 32 + 3 * 32 * 4] = x
    decoded_y1: DynArray[Bytes[32 * 3], 3] = _abi_decode(y,  DynArray[Bytes[32 * 3], 3])
    """
    c = get_contract(code)

    data = b""

    data += (0x20).to_bytes(32, "big")  # DynArray head
    data += (0x03).to_bytes(32, "big")  # DynArray length

    # invalid head - if the length pointed to by this head is 0x60, the decoding function
    # would decode 1 byte over the end of the buffer
    # skip the heads, 1st and 2nd tail to the third tail + 1B
    data += (0x20 * 8 + 0x20 * 3 + 0x01).to_bytes(32, "big")  # inner array0 head

    data += (0x20 * 4 + 0x20 * 3).to_bytes(32, "big")  # inner array1 head
    data += (0x20 * 8 + 0x20 * 3).to_bytes(32, "big")  # inner array2 head

    data += (0x60).to_bytes(32, "big")  # DynArray[Bytes[96], 3][0] length
    data += (0x01).to_bytes(32, "big") * 3  # DynArray[Bytes[96], 3][0] data

    data += (0x60).to_bytes(32, "big")  # DynArray[Bytes[96], 3][1] length
    data += (0x01).to_bytes(32, "big") * 3  # DynArray[Bytes[96], 3][1]  data

    # the invalid head points here + 1B (thus the (0x01) will be considered as the length)
    # we don't revert because of invalid length, but because of invalid head
    # if the length is 0x60, then head + 0x20 (the length word) + 0x60 is 1B
    # over the buffer end
    data += (0x00).to_bytes(32, "big")  # DynArray[Bytes[96], 3][2] length
    data += (0x01).to_bytes(1, "big")
    data += (0x00).to_bytes(31, "big")
    data += (0x03).to_bytes(32, "big") * 2
    with tx_failed():
        c.run(data)


def test_abi_decode_oob_due_to_invalid_size(w3, tx_failed, get_contract):
    code = """
@external
def f(x: Bytes[2 * 32 + 3 * 32  + 3 * 32 * 4]):
    y: Bytes[2 * 32 + 3 * 32 + 3 * 32 * 4] = x
    decoded_y1: DynArray[Bytes[32 * 3], 3] = _abi_decode(y,  DynArray[Bytes[32 * 3], 3])
    """
    c = get_contract(code)
    data = method_id("f(bytes)")
    data += (0x20).to_bytes(32, "big")  # tuple head
    data += (0x0220).to_bytes(32, "big")  # top-level bytes array length
    #data += (0x01E4).to_bytes(32, "big")  # top-level bytes array length

    data += (0x20).to_bytes(32, "big")  # DynArray head
    data += (0x03).to_bytes(32, "big")  # DynArray length

    data += (0x20 * 3).to_bytes(32, "big")  # inner array0 head
    data += (0x20 * 4 + 0x20 * 3).to_bytes(32, "big")  # inner array1 head
    data += (0x20 * 8 + 0x20 * 3).to_bytes(32, "big")  # inner array2 head

    data += (0x60).to_bytes(32, "big")  # DynArray[Bytes[96], 3][0] length
    data += (0x01).to_bytes(32, "big") * 3  # DynArray[Bytes[96], 3][0] data

    data += (0x60).to_bytes(32, "big")  # DynArray[Bytes[96], 3][1] length
    data += (0x01).to_bytes(32, "big") * 3  # DynArray[Bytes[96], 3][1]  data

    data += (0x60).to_bytes(32, "big")  # DynArray[Bytes[96], 3][2] length
    data += (0x01).to_bytes(32, "big") * 3  # DynArray[Bytes[96], 3][2]  data

    with tx_failed():
        w3.eth.send_transaction({"to": c.address, "data": data})


def test_abi_decode_oob_due_to_invalid_head3(tx_failed, get_contract):
    code = """
@external
def bar() -> (uint256, uint256, uint256):
    return (480, 0, 0)

interface A:
    def bar() -> String[32]: nonpayable

@external
def foo():
    x:String[32] = extcall A(self).bar()
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()
