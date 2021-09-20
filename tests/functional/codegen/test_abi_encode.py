# import pytest
from decimal import Decimal


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
