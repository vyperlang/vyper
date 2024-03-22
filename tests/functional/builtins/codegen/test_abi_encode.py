from decimal import Decimal

import pytest
from eth.codecs import abi


# @pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_abi_encode(get_contract):
    code = """
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
# TODO accept struct input once the functionality is available
def abi_encode(
    name: String[64],
    pet_name: String[5],
    pet_address: address,
    pet_id: int128,
    pet_is_furry: bool,
    pet_price: decimal,
    pet_data: uint256[3],
    pet_metadata: bytes32,
    ensure_tuple: bool,
    include_method_id: bool
) -> Bytes[548]:
    human: Human = Human(
      name=name,
      pet=Animal(
        name=pet_name,
        address_=pet_address,
        id_=pet_id,
        is_furry=pet_is_furry,
        price=pet_price,
        data=pet_data,
        metadata=pet_metadata
      ),
    )
    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(human) # default ensure_tuple=True
        return _abi_encode(human, method_id=0xdeadbeef)
    else:
        if not include_method_id:
            return _abi_encode(human, ensure_tuple=False)
        return _abi_encode(human, ensure_tuple=False, method_id=0xdeadbeef)

@external
def abi_encode2(name: String[32], ensure_tuple: bool, include_method_id: bool) -> Bytes[100]:
    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(name) # default ensure_tuple=True
        return _abi_encode(name, method_id=0xdeadbeef)
    else:
        if not include_method_id:
            return _abi_encode(name, ensure_tuple=False)
        return _abi_encode(name, ensure_tuple=False, method_id=0xdeadbeef)

@external
def abi_encode3(x: uint256, ensure_tuple: bool, include_method_id: bool) -> Bytes[36]:

    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(x) # default ensure_tuple=True

        return _abi_encode(x, method_id=0xdeadbeef)

    else:
        if not include_method_id:
            return _abi_encode(x, ensure_tuple=False)

        return _abi_encode(x, ensure_tuple=False, method_id=0xdeadbeef)
    """
    c = get_contract(code)

    method_id = 0xDEADBEEF.to_bytes(4, "big")

    # test each method once each with ensure_tuple set to True and False

    arg = 123
    assert c.abi_encode3(arg, False, False).hex() == abi.encode("uint256", arg).hex()
    assert c.abi_encode3(arg, True, False).hex() == abi.encode("(uint256)", (arg,)).hex()
    assert c.abi_encode3(arg, False, True).hex() == (method_id + abi.encode("uint256", arg)).hex()
    assert (
        c.abi_encode3(arg, True, True).hex() == (method_id + abi.encode("(uint256)", (arg,))).hex()
    )

    arg = "some string"
    assert c.abi_encode2(arg, False, False).hex() == abi.encode("string", arg).hex()
    assert c.abi_encode2(arg, True, False).hex() == abi.encode("(string)", (arg,)).hex()
    assert c.abi_encode2(arg, False, True).hex() == (method_id + abi.encode("string", arg)).hex()
    assert (
        c.abi_encode2(arg, True, True).hex() == (method_id + abi.encode("(string)", (arg,))).hex()
    )

    test_addr = "0x" + b"".join(chr(i).encode("utf-8") for i in range(20)).hex()
    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    human_tuple = (
        "foobar",
        ("vyper", test_addr, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )
    args = tuple([human_tuple[0]] + list(human_tuple[1]))
    human_t = "(string,(string,address,int128,bool,fixed168x10,uint256[3],bytes32))"
    human_encoded = abi.encode(human_t, human_tuple)
    assert c.abi_encode(*args, False, False).hex() == human_encoded.hex()
    assert c.abi_encode(*args, False, True).hex() == (method_id + human_encoded).hex()

    human_encoded = abi.encode(f"({human_t})", (human_tuple,))
    assert c.abi_encode(*args, True, False).hex() == human_encoded.hex()
    assert c.abi_encode(*args, True, True).hex() == (method_id + human_encoded).hex()


@pytest.mark.parametrize("type,value", [("Bytes", b"hello"), ("String", "hello")])
def test_abi_encode_length_failing(get_contract, assert_compile_failed, type, value):
    code = f"""
struct WrappedBytes:
    bs: {type}[6]

@internal
def foo():
    x: WrappedBytes = WrappedBytes(bs={value})
    y: {type}[96] = _abi_encode(x, ensure_tuple=True) # should be Bytes[128]
    """

    assert_compile_failed(lambda: get_contract(code))


def test_abi_encode_dynarray(get_contract):
    code = """
@external
def abi_encode(d: DynArray[uint256, 3], ensure_tuple: bool, include_method_id: bool) -> Bytes[164]:
    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(d) # default ensure_tuple=True
        return _abi_encode(d, method_id=0xdeadbeef)
    else:
        if not include_method_id:
            return _abi_encode(d, ensure_tuple=False)
        return _abi_encode(d, ensure_tuple=False, method_id=0xdeadbeef)
    """
    c = get_contract(code)

    method_id = 0xDEADBEEF.to_bytes(4, "big")

    arg = [123, 456, 789]
    assert c.abi_encode(arg, False, False).hex() == abi.encode("uint256[]", arg).hex()
    assert c.abi_encode(arg, True, False).hex() == abi.encode("(uint256[])", (arg,)).hex()
    assert c.abi_encode(arg, False, True).hex() == (method_id + abi.encode("uint256[]", arg)).hex()
    assert (
        c.abi_encode(arg, True, True).hex() == (method_id + abi.encode("(uint256[])", (arg,))).hex()
    )


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
def test_abi_encode_nested_dynarray(get_contract, args):
    code = """
@external
def abi_encode(
    d: DynArray[DynArray[uint256, 3], 3], ensure_tuple: bool, include_method_id: bool
) -> Bytes[548]:
    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(d) # default ensure_tuple=True
        return _abi_encode(d, method_id=0xdeadbeef)
    else:
        if not include_method_id:
            return _abi_encode(d, ensure_tuple=False)
        return _abi_encode(d, ensure_tuple=False, method_id=0xdeadbeef)
    """
    c = get_contract(code)

    method_id = 0xDEADBEEF.to_bytes(4, "big")

    assert c.abi_encode(args, False, False).hex() == abi.encode("uint256[][]", args).hex()
    assert c.abi_encode(args, True, False).hex() == abi.encode("(uint256[][])", (args,)).hex()
    assert (
        c.abi_encode(args, False, True).hex() == (method_id + abi.encode("uint256[][]", args)).hex()
    )
    assert (
        c.abi_encode(args, True, True).hex()
        == (method_id + abi.encode("(uint256[][])", (args,))).hex()
    )


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
def test_abi_encode_nested_dynarray_2(get_contract, args):
    code = """
@external
def abi_encode(
    d: DynArray[DynArray[DynArray[uint256, 3], 3], 3],
    ensure_tuple: bool,
    include_method_id: bool
) -> Bytes[1700]:
    if ensure_tuple:
        if not include_method_id:
            return _abi_encode(d) # default ensure_tuple=True
        return _abi_encode(d, method_id=0xdeadbeef)
    else:
        if not include_method_id:
            return _abi_encode(d, ensure_tuple=False)
        return _abi_encode(d, ensure_tuple=False, method_id=0xdeadbeef)
    """
    c = get_contract(code)

    method_id = 0xDEADBEEF.to_bytes(4, "big")

    assert c.abi_encode(args, False, False).hex() == abi.encode("uint256[][][]", args).hex()
    assert c.abi_encode(args, True, False).hex() == abi.encode("(uint256[][][])", (args,)).hex()
    assert (
        c.abi_encode(args, False, True).hex()
        == (method_id + abi.encode("uint256[][][]", args)).hex()
    )
    assert (
        c.abi_encode(args, True, True).hex()
        == (method_id + abi.encode("(uint256[][][])", (args,))).hex()
    )


def test_side_effects_evaluation(get_contract):
    contract_1 = """
counter: uint256

@deploy
def __init__():
    self.counter = 0

@external
def get_counter() -> (uint256, String[6]):
    self.counter += 1
    return (self.counter, "hello")
    """

    c = get_contract(contract_1)

    contract_2 = """
interface Foo:
    def get_counter() -> (uint256, String[6]): nonpayable

@external
def foo(addr: address) -> Bytes[164]:
    return _abi_encode(extcall Foo(addr).get_counter(), method_id=0xdeadbeef)
    """

    c2 = get_contract(contract_2)

    method_id = 0xDEADBEEF.to_bytes(4, "big")

    # call to get_counter() should be evaluated only once
    get_counter_encoded = abi.encode("((uint256,string))", ((1, "hello"),))

    assert c2.foo(c.address).hex() == (method_id + get_counter_encoded).hex()


# test _abi_encode in private functions to check buffer overruns
def test_abi_encode_private(get_contract):
    code = """
bytez: Bytes[96]
@internal
def _foo(bs: Bytes[32]):
    self.bytez = _abi_encode(bs)

@external
def foo(bs: Bytes[32]) -> (uint256, Bytes[96]):
    dont_clobber_me: uint256 = max_value(uint256)
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = b"\x00" * 32
    assert c.foo(bs) == [2**256 - 1, abi.encode("(bytes)", (bs,))]


def test_abi_encode_private_dynarray(get_contract):
    code = """
bytez: Bytes[160]
@internal
def _foo(bs: DynArray[uint256, 3]):
    self.bytez = _abi_encode(bs)
@external
def foo(bs: DynArray[uint256, 3]) -> (uint256, Bytes[160]):
    dont_clobber_me: uint256 = max_value(uint256)
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = [1, 2, 3]
    assert c.foo(bs) == [2**256 - 1, abi.encode("(uint256[])", (bs,))]


def test_abi_encode_private_nested_dynarray(get_contract):
    code = """
bytez: Bytes[1696]
@internal
def _foo(bs: DynArray[DynArray[DynArray[uint256, 3], 3], 3]):
    self.bytez = _abi_encode(bs)

@external
def foo(bs: DynArray[DynArray[DynArray[uint256, 3], 3], 3]) -> (uint256, Bytes[1696]):
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
    assert c.foo(bs) == [2**256 - 1, abi.encode("(uint256[][][])", (bs,))]


@pytest.mark.parametrize("empty_literal", ('b""', '""', "empty(Bytes[1])", "empty(String[1])"))
def test_abi_encode_empty_string(get_contract, empty_literal):
    code = f"""
@external
def foo(ensure_tuple: bool) -> Bytes[96]:
    if ensure_tuple:
        return _abi_encode({empty_literal}) # default ensure_tuple=True
    else:
        return _abi_encode({empty_literal}, ensure_tuple=False)
    """

    c = get_contract(code)

    # eth-abi does not encode zero-length string correctly -
    # see https://github.com/ethereum/eth-abi/issues/157
    expected_output = b"\x00" * 32
    assert c.foo(False) == expected_output
    expected_output = b"\x00" * 31 + b"\x20" + b"\x00" * 32
    assert c.foo(True) == expected_output
