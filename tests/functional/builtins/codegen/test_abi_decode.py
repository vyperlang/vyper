import pytest
from eth.codecs import abi

from tests.evm_backends.base_env import EvmError, ExecutionReverted
from tests.utils import decimal_to_int
from vyper.exceptions import ArgumentException, StructureException
from vyper.utils import method_id

TEST_ADDR = "0x" + b"".join(chr(i).encode("utf-8") for i in range(20)).hex()

BUFFER_OVERHEAD = 4 + 2 * 32


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
    a, b, c, d, e = abi_decode(x, (address, int128, bool, decimal, bytes32))
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
    human = abi_decode(x, Human)
    return human
    """

    c = get_contract(contract)

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    args = (TEST_ADDR, -1, True, decimal_to_int("-123.4"), test_bytes32)
    encoding = "(address,int128,bool,int168,bytes32)"
    encoded = abi.encode(encoding, args)
    assert tuple(c.abi_decode(encoded)) == (
        TEST_ADDR,
        -1,
        True,
        decimal_to_int("-123.4"),
        test_bytes32,
    )

    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    human_tuple = (
        "foobar",
        ("vyper", TEST_ADDR, 123, True, decimal_to_int("123.4"), [123, 456, 789], test_bytes32),
    )

    human_t = "((string,(string,address,int128,bool,int168,uint256[3],bytes32)))"
    human_encoded = abi.encode(human_t, (human_tuple,))
    assert c.abi_decode_struct(human_encoded) == (
        "foobar",
        ("vyper", TEST_ADDR, 123, True, decimal_to_int("123.4"), [123, 456, 789], test_bytes32),
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
def test_abi_decode_single(get_contract, expected, input_len, output_typ, abi_typ, unwrap_tuple):
    contract = f"""
@external
def foo(x: Bytes[{input_len}]) -> {output_typ}:
    a: {output_typ} = abi_decode(x, {output_typ}, unwrap_tuple={unwrap_tuple})
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
    a, b = abi_decode(x, ({output_typ1}, {output_typ2}), unwrap_tuple={unwrap_tuple})
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
    a = abi_decode(x, DynArray[DynArray[uint256, 3], 3], unwrap_tuple={unwrap_tuple})
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
    a = abi_decode(
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
    assert c.foo(encoded) == (2**256 - 1, bs)


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
    assert c.foo(encoded) == (2**256 - 1, bs)


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
    "output_typ1,output_typ2,input_,error,error_property",
    [
        ("DynArray[uint256, 3]", "uint256", b"", ExecutionReverted, ""),
        ("DynArray[uint256, 3]", "uint256", b"\x01" * 128, EvmError, "OUT_OF_GAS_ERROR"),
        ("Bytes[5]", "address", b"", ExecutionReverted, ""),
        ("Bytes[5]", "address", b"\x01" * 128, EvmError, "OUT_OF_GAS_ERROR"),
    ],
)
def test_clamper_dynamic_tuple(
    get_contract, tx_failed, output_typ1, output_typ2, input_, error, error_property, env
):
    contract = f"""
@external
def abi_decode(x: Bytes[224]) -> ({output_typ1}, {output_typ2}):
    a: {output_typ1} = empty({output_typ1})
    b: {output_typ2} = empty({output_typ2})
    a, b = _abi_decode(x, ({output_typ1}, {output_typ2}))
    return a, b
    """
    c = get_contract(contract)
    with tx_failed(error, exc_text=getattr(env, error_property, None)):
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


def _abi_payload_from_tuple(payload: tuple[int | bytes, ...], max_sz: int) -> bytes:
    ret = b"".join(p.to_bytes(32, "big") if isinstance(p, int) else p for p in payload)
    assert len(ret) <= max_sz
    return ret


def _replicate(value: int, count: int) -> tuple[int, ...]:
    return (value,) * count


def test_abi_decode_arithmetic_overflow(env, tx_failed, get_contract):
    # test based on GHSA-9p8r-4xp4-gw5w:
    # https://github.com/vyperlang/vyper/security/advisories/GHSA-9p8r-4xp4-gw5w#advisory-comment-91841
    # buf + head causes arithmetic overflow
    buffer_size = 32 * 3
    code = f"""
@external
def f(x: Bytes[{buffer_size}]):
    a: Bytes[32] = b"foo"
    y: Bytes[{buffer_size}] = x

    decoded_y1: Bytes[32] = _abi_decode(y, Bytes[32])
    a = b"bar"
    decoded_y2: Bytes[32] = _abi_decode(y, Bytes[32])
    # original POC:
    # assert decoded_y1 != decoded_y2
    """
    c = get_contract(code)

    tuple_head_ofst = 0x20
    parent_array_len = 0x60
    msg_call_overhead = (method_id("f(bytes)"), tuple_head_ofst, parent_array_len)

    data = _abi_payload_from_tuple(msg_call_overhead, BUFFER_OVERHEAD)

    # parent payload - this word will be considered as the head of the
    # abi-encoded inner array and it will be added to base ptr leading to an
    # arithmetic overflow
    buffer_payload = (2**256 - 0x60,)

    data += _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        env.message_call(c.address, data=data)


def test_abi_decode_nonstrict_head(env, get_contract):
    # data isn't strictly encoded - head is 0x21 instead of 0x20
    # but the head + length is still within runtime bounds of the parent buffer
    buffer_size = 32 * 5
    code = f"""
@external
def f(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    a: Bytes[32] = b"a"
    decoded_y1: DynArray[uint256, 3] = _abi_decode(y, DynArray[uint256, 3])
    assert len(decoded_y1) == 1 and decoded_y1[0] == 0
    a = b"aaaa"
    decoded_y1 = _abi_decode(y, DynArray[uint256, 3])
    assert len(decoded_y1) == 1 and decoded_y1[0] == 0
    """
    c = get_contract(code)

    tuple_head_ofst = 0x20
    parent_array_len = 0xA0
    msg_call_overhead = (method_id("f(bytes)"), tuple_head_ofst, parent_array_len)

    data = _abi_payload_from_tuple(msg_call_overhead, BUFFER_OVERHEAD)

    buffer_payload = (
        # head should be 0x20 but is 0x21 thus the data isn't strictly encoded
        0x21,
        # we don't want to revert on invalid length, so set this to 0
        # the first byte of payload will be considered as the length
        0x00,
        (0x01).to_bytes(1, "big"),  # will be considered as the length=1
        (0x00).to_bytes(31, "big"),
        *_replicate(0x03, 2),
    )

    data += _abi_payload_from_tuple(buffer_payload, buffer_size)

    env.message_call(c.address, data=data)


def test_abi_decode_child_head_points_to_parent(tx_failed, get_contract):
    # data isn't strictly encoded and the head for the inner array
    # skips the corresponding payload and points to other valid section of the
    # parent buffer
    buffer_size = 14 * 32
    code = f"""
@external
def run(x: Bytes[{buffer_size}]) -> DynArray[DynArray[DynArray[uint256, 2], 1], 2]:
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[DynArray[DynArray[uint256, 2], 1], 2] = _abi_decode(
        y,
        DynArray[DynArray[DynArray[uint256, 2], 1], 2]
    )
    return decoded_y1
    """
    c = get_contract(code)
    # encode [[[1, 1]], [[2, 2]]] and modify the head for [1, 1]
    # to actually point to [2, 2]
    buffer_payload = (
        0x20,  # top-level array head
        0x02,  # top-level array length
        0x40,  # head of DAr[DAr[DAr, uint256]]][0]
        0xE0,  # head of DAr[DAr[DAr, uint256]]][1]
        0x01,  # DAr[DAr[DAr, uint256]]][0] length
        # head of DAr[DAr[DAr, uint256]]][0][0]
        # points to DAr[DAr[DAr, uint256]]][1][0]
        0x20 * 6,
        0x02,  # DAr[DAr[DAr, uint256]]][0][0] length
        0x01,  # DAr[DAr[DAr, uint256]]][0][0][0]
        0x01,  # DAr[DAr[DAr, uint256]]][0][0][1]
        0x01,  # DAr[DAr[DAr, uint256]]][1] length
        0x20,  # DAr[DAr[DAr, uint256]]][1][0] head
        0x02,  # DAr[DAr[DAr, uint256]]][1][0] length
        0x02,  # DAr[DAr[DAr, uint256]]][1][0][0]
        0x02,  # DAr[DAr[DAr, uint256]]][1][0][1]
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    res = c.run(data)
    assert res == [[[2, 2]], [[2, 2]]]


def test_abi_decode_nonstrict_head_oob(tx_failed, get_contract):
    # data isn't strictly encoded and (non_strict_head + len(DynArray[..][2])) > parent_static_sz
    # thus decoding the data pointed to by the head would cause an OOB read
    # non_strict_head + length == parent + parent_static_sz + 1
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[Bytes[32 * 3], 3] = _abi_decode(y,  DynArray[Bytes[32 * 3], 3])
    """
    c = get_contract(code)

    buffer_payload = (
        0x20,  # DynArray head
        0x03,  # DynArray length
        # non_strict_head - if the length pointed to by this head is 0x60
        # (which is valid length for the Bytes[32*3] buffer), the decoding
        # function  would decode 1 byte over the end of the buffer
        # we define the non_strict_head as:
        # skip the remaining heads, 1st and 2nd tail
        # to the third tail + 1B
        0x20 * 8 + 0x20 * 3 + 0x01,  # inner array0 head
        0x20 * 4 + 0x20 * 3,  # inner array1 head
        0x20 * 8 + 0x20 * 3,  # inner array2 head
        0x60,  # DynArray[Bytes[96], 3][0] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][0] data
        0x60,  # DynArray[Bytes[96], 3][1] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][1]  data
        # the invalid head points here + 1B (thus the length is 0x60)
        # we don't revert because of invalid length, but because head+length is OOB
        0x00,  # DynArray[Bytes[96], 3][2] length
        (0x60).to_bytes(1, "big"),
        (0x00).to_bytes(31, "big"),
        *_replicate(0x03, 2),
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_nonstrict_head_oob2(tx_failed, get_contract):
    # same principle as in Test_abi_decode_nonstrict_head_oob
    # but adapted for dynarrays
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[DynArray[uint256, 3], 3] = _abi_decode(
        y,
        DynArray[DynArray[uint256, 3], 3]
    )
    """
    c = get_contract(code)

    buffer_payload = (
        0x20,  # DynArray head
        0x03,  # DynArray length
        (0x20 * 8 + 0x20 * 3 + 0x01),  # inner array0 head
        (0x20 * 4 + 0x20 * 3),  # inner array1 head
        (0x20 * 8 + 0x20 * 3),  # inner array2 head
        0x03,  # DynArray[..][0] length
        *_replicate(0x01, 3),  # DynArray[..][0] data
        0x03,  # DynArray[..][1] length
        *_replicate(0x01, 3),  # DynArray[..][1] data
        0x00,  # DynArray[..][2] length
        (0x03).to_bytes(1, "big"),
        (0x00).to_bytes(31, "big"),
        *_replicate(0x01, 2),  # DynArray[..][2] data
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_head_pointing_outside_buffer(tx_failed, get_contract):
    # the head points completely outside the buffer
    buffer_size = 3 * 32
    code = f"""
@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: Bytes[32] = _abi_decode(y, Bytes[32])
    """
    c = get_contract(code)

    buffer_payload = (0x80, 0x20, 0x01)
    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_bytearray_clamp(tx_failed, get_contract):
    # data has valid encoding, but the length of DynArray[Bytes[96], 3][0] is
    # set to 0x61
    # and thus the decoding should fail on bytestring clamp
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[Bytes[32 * 3], 3] = _abi_decode(y,  DynArray[Bytes[32 * 3], 3])
    """
    c = get_contract(code)

    buffer_payload = (
        0x20,  # DynArray head
        0x03,  # DynArray length
        0x20 * 3,  # inner array0 head
        0x20 * 4 + 0x20 * 3,  # inner array1 head
        0x20 * 8 + 0x20 * 3,  # inner array2 head
        # invalid length - should revert on bytestring clamp
        0x61,  # DynArray[Bytes[96], 3][0] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][0] data
        0x60,  # DynArray[Bytes[96], 3][1] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][1] data
        0x60,  # DynArray[Bytes[96], 3][2] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][2] data
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_runtimesz_oob(tx_failed, get_contract, env):
    # provide enough data, but set the runtime size to be smaller than the
    # actual size so after y: [..] = x, y will have the incorrect size set and
    # only part of the original data will be copied. This will cause oob read
    # outside the runtime sz (but still within static size of the buffer)
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def f(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[Bytes[32 * 3], 3] = _abi_decode(y,  DynArray[Bytes[32 * 3], 3])
    """
    c = get_contract(code)

    msg_call_overhead = (
        method_id("f(bytes)"),
        0x20,  # tuple head
        # the correct size is 0x220 (2*32+3*32+4*3*32)
        # therefore we will decode after the end of runtime size (but still
        # within the buffer)
        0x01E4,  # top-level bytes array length
    )

    data = _abi_payload_from_tuple(msg_call_overhead, BUFFER_OVERHEAD)

    buffer_payload = (
        0x20,  # DynArray head
        0x03,  # DynArray length
        0x20 * 3,  # inner array0 head
        0x20 * 4 + 0x20 * 3,  # inner array1 head
        0x20 * 8 + 0x20 * 3,  # inner array2 head
        0x60,  # DynArray[Bytes[96], 3][0] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][0] data
        0x60,  # DynArray[Bytes[96], 3][1] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][1] data
        0x60,  # DynArray[Bytes[96], 3][2] length
        *_replicate(0x01, 3),  # DynArray[Bytes[96], 3][2] data
    )

    data += _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        env.message_call(c.address, data=data)


def test_abi_decode_runtimesz_oob2(tx_failed, get_contract, env):
    # same principle as in test_abi_decode_runtimesz_oob
    # but adapted for dynarrays
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def f(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[DynArray[uint256, 3], 3] = _abi_decode(
        y,
        DynArray[DynArray[uint256, 3], 3]
    )
    """
    c = get_contract(code)

    msg_call_overhead = (
        method_id("f(bytes)"),
        0x20,  # tuple head
        0x01E4,  # top-level bytes array length
    )

    data = _abi_payload_from_tuple(msg_call_overhead, BUFFER_OVERHEAD)

    buffer_payload = (
        0x20,  # DynArray head
        0x03,  # DynArray length
        0x20 * 3,  # inner array0 head
        0x20 * 4 + 0x20 * 3,  # inner array1 head
        0x20 * 8 + 0x20 * 3,  # inner array2 head
        0x03,  # DynArray[..][0] length
        *_replicate(0x01, 3),  # DynArray[..][0] data
        0x03,  # DynArray[..][1] length
        *_replicate(0x01, 3),  # DynArray[..][1] data
        0x03,  # DynArray[..][2] length
        *_replicate(0x01, 3),  # DynArray[..][2] data
    )

    data += _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        env.message_call(c.address, data=data)


def test_abi_decode_head_roundtrip(tx_failed, get_contract, env):
    # top-level head in the y2 buffer points to the y1 buffer
    # and y1 contains intermediate heads pointing to the inner arrays
    # which are in turn in the y2 buffer
    # NOTE: the test is memory allocator dependent - we assume that y1 and y2
    # have the 800 & 960 addresses respectively
    buffer_size1 = 4 * 32
    buffer_size2 = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x1: Bytes[{buffer_size1}], x2: Bytes[{buffer_size2}]):
    y1: Bytes[{buffer_size1}] = x1 # addr: 800
    y2: Bytes[{buffer_size2}] = x2 # addr: 960
    decoded_y1: DynArray[DynArray[uint256, 3], 3] = _abi_decode(
        y2,
        DynArray[DynArray[uint256, 3], 3]
    )
    """
    c = get_contract(code)

    buffer_payload = (
        0x03,  # DynArray length
        # distance to y2 from y1 is 160
        160 + 0x20 + 0x20 * 3,  # points to DynArray[..][0] length
        160 + 0x20 + 0x20 * 4 + 0x20 * 3,  # points to DynArray[..][1] length
        160 + 0x20 + 0x20 * 8 + 0x20 * 3,  # points to DynArray[..][2] length
    )

    data1 = _abi_payload_from_tuple(buffer_payload, buffer_size1)

    buffer_payload = (
        # (960 + (2**256 - 160)) % 2**256 == 800, ie will roundtrip to y1
        2**256 - 160,  # points to y1
        0x03,  # DynArray length (not used)
        0x20 * 3,  # inner array0 head
        0x20 * 4 + 0x20 * 3,  # inner array1 head
        0x20 * 8 + 0x20 * 3,  # inner array2 head
        0x03,  # DynArray[..][0] length
        *_replicate(0x01, 3),  # DynArray[..][0] data
        0x03,  # DynArray[..][1] length
        *_replicate(0x02, 3),  # DynArray[..][1] data
        0x03,  # DynArray[..][2] length
        *_replicate(0x03, 3),  # DynArray[..][2] data
    )

    data2 = _abi_payload_from_tuple(buffer_payload, buffer_size2)

    with tx_failed():
        c.run(data1, data2)


def test_abi_decode_merge_head_and_length(get_contract):
    # compress head and length into 33B
    buffer_size = 32 * 2 + 8 * 32
    code = f"""
@external
def run(x: Bytes[{buffer_size}]) -> Bytes[{buffer_size}]:
    y: Bytes[{buffer_size}] = x
    decoded_y1: Bytes[256] = _abi_decode(y, Bytes[256])
    return decoded_y1
    """
    c = get_contract(code)

    buffer_payload = (0x01, (0x00).to_bytes(1, "big"), *_replicate(0x00, 8))

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    res = c.run(data)

    assert res == bytes(256)


def test_abi_decode_extcall_invalid_head(tx_failed, get_contract):
    # the head returned from the extcall is set to invalid value of 480
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


def test_abi_decode_extcall_oob(tx_failed, get_contract):
    # the head returned from the extcall is 1 byte bigger than expected
    # thus we'll take the last 31 0-bytes from tuple[1] and the 1st byte from
    # tuple[2] and consider this the length - thus the length is 2**5
    # and thus we'll read 1B over the buffer end (33 + 32 + 32)
    code = """
@external
def bar() -> (uint256, uint256, uint256):
    return (33, 0, 2**(5+248))

interface A:
    def bar() -> String[32]: nonpayable

@external
def foo():
    x:String[32] = extcall A(self).bar()
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()


def test_abi_decode_extcall_runtimesz_oob(tx_failed, get_contract):
    # the runtime size (33) is bigger than the actual payload (32 bytes)
    # thus we'll read 1 byte over the runtime size - but still within the
    # static size of the buffer
    code = """
@external
def bar() -> (uint256, uint256, uint256):
    return (32, 33, 0)

interface A:
    def bar() -> String[64]: nonpayable

@external
def foo():
    x:String[64] = extcall A(self).bar()
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()


def test_abi_decode_extcall_truncate_returndata(get_contract):
    # return more data than expected
    # the truncated data is still valid
    code = """
@external
def bar() -> (uint256, uint256, uint256, uint256):
    return (32, 32, 36, 36)

interface A:
    def bar() -> Bytes[32]: nonpayable

@external
def foo() -> Bytes[32]:
    return extcall A(self).bar()
    """
    c = get_contract(code)
    res = c.foo()

    assert res == (36).to_bytes(32, "big")


def test_abi_decode_extcall_truncate_returndata2(tx_failed, get_contract):
    # return more data than expected
    # after truncation the data is invalid because the length is too big
    # wrt to the static size of the buffer
    code = """
@external
def bar() -> (uint256, uint256, uint256, uint256):
    return (32, 33, 36, 36)

interface A:
    def bar() -> Bytes[32]: nonpayable

@external
def foo():
    x:Bytes[32] = extcall A(self).bar()
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()


def test_abi_decode_extcall_return_nodata(tx_failed, get_contract):
    code = """
@external
def bar():
    return

interface A:
    def bar() -> Bytes[32]: nonpayable

@external
def foo():
    x:Bytes[32] = extcall A(self).bar()
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()


def test_abi_decode_extcall_array_oob(tx_failed, get_contract):
    # same as in test_abi_decode_extcall_oob
    # DynArray[..][1] head isn't strict and points 1B over
    # thus the 1st B of 2**(5+248) is considered as the length (32)
    # thus we try to decode 1B over the buffer end
    code = """
@external
def bar() -> (uint256, uint256, uint256, uint256, uint256, uint256, uint256, uint256):
    return (
        32, # DynArray head
        2,  # DynArray length
        32 * 2,  # DynArray[..][0] head
        32 * 2 + 32 * 2 + 1, # DynArray[..][1] head
        32, # DynArray[..][0] length
        0,  # DynArray[..][0] data
        0,  # DynArray[..][1] length
        2**(5+248) # DynArray[..][1] length (and data)
    )

interface A:
    def bar() -> DynArray[Bytes[32], 2]: nonpayable

@external
def run():
    x: DynArray[Bytes[32], 2] = extcall A(self).bar()
    """
    c = get_contract(code)

    with tx_failed():
        c.run()


def test_abi_decode_extcall_array_oob_with_truncate(tx_failed, get_contract):
    # same as in test_abi_decode_extcall_oob but we also return more data than expected
    # DynArray[..][1] head isn't strict and points 1B over
    # thus the 1st B of 2**(5+248) is considered as the length (32)
    # thus we try to decode 1B over the buffer end
    code = """
@external
def bar() -> (uint256, uint256, uint256, uint256, uint256, uint256, uint256, uint256, uint256):
    return (
        32, # DynArray head
        2,  # DynArray length
        32 * 2,  # DynArray[..][0] head
        32 * 2 + 32 * 2 + 1, # DynArray[..][1] head
        32, # DynArray[..][0] length
        0,  # DynArray[..][0] data
        0,  # DynArray[..][1] length
        2**(5+248), # DynArray[..][1] length (and data)
        0   # extra data
    )

interface A:
    def bar() -> DynArray[Bytes[32], 2]: nonpayable

@external
def run():
    x: DynArray[Bytes[32], 2] = extcall A(self).bar()
    """
    c = get_contract(code)

    with tx_failed():
        c.run()


def test_abi_decode_extcall_empty_array(get_contract):
    code = """
@external
def bar() -> (uint256, uint256):
    return 32, 0

interface A:
    def bar() -> DynArray[Bytes[32], 2]: nonpayable

@external
def run() -> DynArray[Bytes[32], 2]:
    return extcall A(self).bar()
    """
    c = get_contract(code)

    res = c.run()

    assert res == []


def test_abi_decode_extcall_complex_empty_dynarray(get_contract):
    # 5th word of the payload points to the last word of the payload
    # which is considered the length of the Point.y array
    # because the length is 0, the decoding should succeed
    code = """
struct Point:
    x: uint256
    y: DynArray[uint256, 2]
    z: uint256

@external
def bar() -> (uint256, uint256, uint256, uint256, uint256, uint256):
    return 32, 1, 32, 1, 64, 0

interface A:
    def bar() -> DynArray[Point, 2]: nonpayable

@external
def run() -> DynArray[Point, 2]:
    return extcall A(self).bar()
    """
    c = get_contract(code)

    res = c.run()

    assert res == [(1, [], 0)]


def test_abi_decode_extcall_complex_empty_dynarray2(tx_failed, get_contract):
    # top-level head points 1B over the runtime buffer end
    # thus the decoding should fail although the length is 0
    code = """
struct Point:
    x: uint256
    y: DynArray[uint256, 2]
    z: uint256

@external
def bar() -> (uint256, uint256):
    return 33, 0

interface A:
    def bar() -> DynArray[Point, 2]: nonpayable

@external
def run():
    x: DynArray[Point, 2] = extcall A(self).bar()
    """
    c = get_contract(code)

    with tx_failed():
        c.run()


def test_abi_decode_extcall_zero_len_array2(get_contract):
    code = """
@external
def bar() -> (uint256, uint256):
    return 0, 0

interface A:
    def bar() -> DynArray[Bytes[32], 2]: nonpayable

@external
def run() -> DynArray[Bytes[32], 2]:
    return extcall A(self).bar()
    """
    c = get_contract(code)

    res = c.run()

    assert res == []


def test_abi_decode_top_level_head_oob(tx_failed, get_contract):
    buffer_size = 256
    code = f"""
@external
def run(x: Bytes[{buffer_size}], y: uint256):
    player_lost: bool = empty(bool)

    if y == 1:
        player_lost = True

    decoded: DynArray[Bytes[1], 2] = empty(DynArray[Bytes[1], 2])
    decoded = _abi_decode(x, DynArray[Bytes[1], 2])
    """
    c = get_contract(code)

    # head points over the buffer end
    bufffer_payload = (0x0100, *_replicate(0x00, 7))

    data = _abi_payload_from_tuple(bufffer_payload, buffer_size)

    with tx_failed():
        c.run(data, 1)

    with tx_failed():
        c.run(data, 0)


def test_abi_decode_dynarray_complex_insufficient_data(env, tx_failed, get_contract):
    buffer_size = 32 * 8
    code = f"""
struct Point:
    x: uint256
    y: uint256

@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[Point, 3] = _abi_decode(y, DynArray[Point, 3])
    """
    c = get_contract(code)

    # runtime buffer has insufficient size - we decode 3 points, but provide only
    # 3 * 32B of payload
    buffer_payload = (0x20, 0x03, *_replicate(0x03, 3))

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_dynarray_complex2(env, tx_failed, get_contract):
    # point head to the 1st 0x01 word (ie the length)
    # but size of the point is 3 * 32B, thus we'd decode 2B over the buffer end
    buffer_size = 32 * 8
    code = f"""
struct Point:
    x: uint256
    y: uint256
    z: uint256


@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[32 * 11] = x
    decoded_y1: DynArray[Point, 2] = _abi_decode(y, DynArray[Point, 2])
    """
    c = get_contract(code)

    buffer_payload = (
        0xC0,  # points to the 1st 0x01 word (ie the length)
        *_replicate(0x03, 5),
        *_replicate(0x01, 2),
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_complex_empty_dynarray(env, tx_failed, get_contract):
    # point head to the last word of the payload
    # this will be the length, but because it's set to 0, the decoding should succeed
    buffer_size = 32 * 16
    code = f"""
struct Point:
    x: uint256
    y: DynArray[uint256, 2]
    z: uint256


@external
def run(x: Bytes[{buffer_size}]) -> DynArray[Point, 2]:
    y: Bytes[{buffer_size}] = x
    return _abi_decode(y, DynArray[Point, 2])
    """
    c = get_contract(code)

    buffer_payload = (
        0x20,
        0x01,
        0x20,
        0x01,
        0xA0,  # points to the last word of the payload
        0x04,
        0x02,
        0x02,
        0x00,  # length is 0, so decoding should succeed
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    res = c.run(data)

    assert res == [(1, [], 4)]


def test_abi_decode_complex_arithmetic_overflow(tx_failed, get_contract):
    # inner head roundtrips due to arithmetic overflow
    buffer_size = 32 * 16
    code = f"""
struct Point:
    x: uint256
    y: DynArray[uint256, 2]
    z: uint256


@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[Point, 2] = _abi_decode(y, DynArray[Point, 2])
    """
    c = get_contract(code)

    buffer_payload = (
        0x20,
        0x01,
        0x20,
        0x01,  # both Point.x and Point.y length
        2**256 - 0x20,  # points to the "previous" word of the payload
        0x04,
        0x02,
        0x02,
        0x00,
    )

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_abi_decode_empty_toplevel_dynarray(get_contract):
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x: Bytes[{buffer_size}]) -> DynArray[DynArray[uint256, 3], 3]:
    y: Bytes[{buffer_size}] = x
    assert len(y) == 2 * 32
    decoded_y1: DynArray[DynArray[uint256, 3], 3] = _abi_decode(
        y,
        DynArray[DynArray[uint256, 3], 3]
    )
    return decoded_y1
    """
    c = get_contract(code)

    buffer_payload = (0x20, 0x00)  # DynArray head, DynArray length

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    res = c.run(data)

    assert res == []


def test_abi_decode_invalid_toplevel_dynarray_head(tx_failed, get_contract):
    # head points 1B over the bounds of the runtime buffer
    buffer_size = 2 * 32 + 3 * 32 + 3 * 32 * 4
    code = f"""
@external
def run(x: Bytes[{buffer_size}]):
    y: Bytes[{buffer_size}] = x
    decoded_y1: DynArray[DynArray[uint256, 3], 3] = _abi_decode(
        y,
        DynArray[DynArray[uint256, 3], 3]
    )
    """
    c = get_contract(code)

    # head points 1B over the bounds of the runtime buffer
    buffer_payload = (0x21, 0x00)  # DynArray head, DynArray length

    data = _abi_payload_from_tuple(buffer_payload, buffer_size)

    with tx_failed():
        c.run(data)


def test_nested_invalid_dynarray_head(get_contract, tx_failed):
    buffer_size = 320
    code = f"""
@nonpayable
@external
def foo(x:Bytes[{buffer_size}]):
    if True:
        a: Bytes[320-32] = b''

        # make the word following the buffer x_mem dirty to make a potential
        # OOB revert
        fake_head: uint256 = 32
    x_mem: Bytes[{buffer_size}] = x

    y: DynArray[DynArray[uint256, 2], 2] = _abi_decode(x_mem,DynArray[DynArray[uint256, 2], 2])

@nonpayable
@external
def bar(x:Bytes[{buffer_size}]):
    x_mem: Bytes[{buffer_size}] = x

    y:DynArray[DynArray[uint256, 2], 2] = _abi_decode(x_mem,DynArray[DynArray[uint256, 2], 2])
    """
    c = get_contract(code)

    encoded = (0x20, 0x02)  # head of the dynarray  # len of outer
    inner = (
        0x0,  # head1
        # 0x0,  # head2
    )

    encoded = _abi_payload_from_tuple(encoded + inner, buffer_size)
    with tx_failed():
        c.foo(encoded)  # revert
    with tx_failed():
        c.bar(encoded)  # return [[],[]]


def test_static_outer_type_invalid_heads(get_contract, tx_failed):
    buffer_size = 320
    code = f"""
@nonpayable
@external
def foo(x:Bytes[{buffer_size}]):
    x_mem: Bytes[{buffer_size}] = x
    y:DynArray[uint256, 2][2] = _abi_decode(x_mem,DynArray[uint256, 2][2])

@nonpayable
@external
def bar(x:Bytes[{buffer_size}]):
    if True:
        a: Bytes[160] = b''
        # write stuff here to make the call revert in case decode do
        # an out of bound access:
        fake_head: uint256 = 32
    x_mem: Bytes[{buffer_size}] = x
    y:DynArray[uint256, 2][2] = _abi_decode(x_mem,DynArray[uint256, 2][2])
    """
    c = get_contract(code)

    encoded = (0x20,)  # head of the static array
    inner = (
        0x00,  # head of the first dynarray
        # 0x00,  # head of the second dynarray
    )

    encoded = _abi_payload_from_tuple(encoded + inner, buffer_size)

    with tx_failed():
        c.foo(encoded)
    with tx_failed():
        c.bar(encoded)


def test_abi_decode_max_size(get_contract, tx_failed):
    # test case where the payload is "too large" than the max size
    # of abi encoding the type. this can happen when the payload is
    # "sparse" and has garbage bytes in between the static and dynamic
    # sections
    buffer_size = 1000
    code = f"""
@external
def foo(a:Bytes[{buffer_size}]):
    v: DynArray[uint256, 1] = _abi_decode(a,DynArray[uint256, 1])
    """
    c = get_contract(code)

    payload = (
        0xA0,  # head
        0x00,  # garbage
        0x00,  # garbage
        0x00,  # garbage
        0x00,  # garbage
        0x01,  # len
        0x12,  # elem1
    )

    with tx_failed():
        c.foo(_abi_payload_from_tuple(payload, buffer_size))


# returndatasize check for uint256
def test_returndatasize_check(get_contract, tx_failed):
    code = """
@external
def bar():
    pass

interface A:
    def bar() -> uint256: nonpayable

@external
def run() -> uint256:
    return extcall A(self).bar()
    """
    c = get_contract(code)

    with tx_failed():
        c.run()
