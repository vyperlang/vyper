# import pytest
from decimal import Decimal


# @pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_abi_encode(get_contract, abi_encode):
    code = """
struct Animal:
  name: String[64]
  id_: int128
  price: decimal

struct Human:
  name: String[32]
  pet: Animal

@external
# TODO accept struct input once the functionality is available
def abi_encode(
    name: String[32],
    pet_name: String[64],
    pet_id: int128,
    pet_price: decimal,
    ensure_tuple: bool=True
) -> Bytes[256]:
    human: Human = Human({
      name: name,
      pet: Animal({
        name: pet_name,
        id_: pet_id,
        price: pet_price
      })
    })
    if ensure_tuple:
        return _abi_encode(human, ensure_tuple=True)
    else:
        return _abi_encode(human, ensure_tuple=False)
@external
def abi_encode2(name: String[32], ensure_tuple: bool = True) -> Bytes[96]:
    if ensure_tuple:
        return _abi_encode(name, ensure_tuple=True)
    else:
        return _abi_encode(name, ensure_tuple=False)
@external
def abi_encode3(x: uint256, ensure_tuple: bool = True) -> Bytes[32]:
    if ensure_tuple:
        return _abi_encode(x, ensure_tuple=True)
    else:
        return _abi_encode(x, ensure_tuple=False)
    """
    c = get_contract(code)

    # test each method once each with ensure_tuple set to True and False

    arg = 123
    assert c.abi_encode3(arg, False).hex() == abi_encode("uint256", arg).hex()
    assert c.abi_encode3(arg, True).hex() == abi_encode("(uint256)", (arg,)).hex()

    arg = "some string"
    assert c.abi_encode2(arg, False).hex() == abi_encode("string", arg).hex()
    assert c.abi_encode2(arg, True).hex() == abi_encode("(string)", (arg,)).hex()

    args = ("foobar", "vyper", 123, Decimal("123.4"))
    human_tuple = (
        "foobar",
        ("vyper", 123, Decimal("123.4")),
    )  # TODO use convenience method to convert from human
    human_t = "(string,(string,int128,fixed168x10))"
    human_encoded = abi_encode(human_t, human_tuple)
    assert c.abi_encode(*args, False).hex() == human_encoded.hex()

    human_encoded = abi_encode(f"({human_t})", (human_tuple,))
    assert c.abi_encode(*args, True).hex() == human_encoded.hex()
