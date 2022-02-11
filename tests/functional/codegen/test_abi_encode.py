from decimal import Decimal

import pytest


# @pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_abi_encode(get_contract, abi_encode):
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
    human: Human = Human({
      name: name,
      pet: Animal({
        name: pet_name,
        address_: pet_address,
        id_: pet_id,
        is_furry: pet_is_furry,
        price: pet_price,
        data: pet_data,
        metadata: pet_metadata
      }),
    })
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

    method_id = 0xDEADBEEF .to_bytes(4, "big")

    # test each method once each with ensure_tuple set to True and False

    arg = 123
    assert c.abi_encode3(arg, False, False).hex() == abi_encode("uint256", arg).hex()
    assert c.abi_encode3(arg, True, False).hex() == abi_encode("(uint256)", (arg,)).hex()
    assert c.abi_encode3(arg, False, True).hex() == (method_id + abi_encode("uint256", arg)).hex()
    assert (
        c.abi_encode3(arg, True, True).hex() == (method_id + abi_encode("(uint256)", (arg,))).hex()
    )

    arg = "some string"
    assert c.abi_encode2(arg, False, False).hex() == abi_encode("string", arg).hex()
    assert c.abi_encode2(arg, True, False).hex() == abi_encode("(string)", (arg,)).hex()
    assert c.abi_encode2(arg, False, True).hex() == (method_id + abi_encode("string", arg)).hex()
    assert (
        c.abi_encode2(arg, True, True).hex() == (method_id + abi_encode("(string)", (arg,))).hex()
    )

    test_addr = b"".join(chr(i).encode("utf-8") for i in range(20))
    test_bytes32 = b"".join(chr(i).encode("utf-8") for i in range(32))
    human_tuple = (
        "foobar",
        ("vyper", test_addr, 123, True, Decimal("123.4"), [123, 456, 789], test_bytes32),
    )
    args = tuple([human_tuple[0]] + list(human_tuple[1]))
    human_t = "(string,(string,address,int128,bool,fixed168x10,uint256[3],bytes32))"
    human_encoded = abi_encode(human_t, human_tuple)
    assert c.abi_encode(*args, False, False).hex() == human_encoded.hex()
    assert c.abi_encode(*args, False, True).hex() == (method_id + human_encoded).hex()

    human_encoded = abi_encode(f"({human_t})", (human_tuple,))
    assert c.abi_encode(*args, True, False).hex() == human_encoded.hex()
    assert c.abi_encode(*args, True, True).hex() == (method_id + human_encoded).hex()


@pytest.mark.parametrize("type,value", [("Bytes", b"hello"), ("String", "hello")])
def test_abi_encode_length_failing(get_contract, assert_compile_failed, type, value):
    code = f"""
struct WrappedBytes:
    bs: {type}[6]

@internal
def foo():
    x: WrappedBytes = WrappedBytes({{bs: {value}}})
    y: {type}[96] = _abi_encode(x, ensure_tuple=True) # should be Bytes[128]
    """

    assert_compile_failed(lambda: get_contract(code))


def test_side_effects_evaluation(get_contract, abi_encode):
    contract_1 = """
counter: uint256

@external
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
    return _abi_encode(Foo(addr).get_counter(), method_id=0xdeadbeef)
    """

    c2 = get_contract(contract_2)

    method_id = 0xDEADBEEF .to_bytes(4, "big")

    # call to get_counter() should be evaluated only once
    get_counter_encoded = abi_encode("((uint256,string))", ((1, "hello"),))

    assert c2.foo(c.address).hex() == (method_id + get_counter_encoded).hex()


# test _abi_encode in private functions to check buffer overruns
def test_abi_encode_private(get_contract, abi_encode):
    code = """
bytez: Bytes[96]
@internal
def _foo(bs: Bytes[32]):
    self.bytez = _abi_encode(bs)

@external
def foo(bs: Bytes[32]) -> (uint256, Bytes[96]):
    dont_clobber_me: uint256 = MAX_UINT256
    self._foo(bs)
    return dont_clobber_me, self.bytez
    """
    c = get_contract(code)
    bs = "0" * 32
    assert c.foo(bs) == [2 ** 256 - 1, abi_encode("(bytes)", (bs,))]
