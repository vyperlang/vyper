import pytest


def test_nested_struct(get_contract):
    code = """
struct Animal:
    location: address
    fur: String[32]

struct Human:
    location: address
    animal: Animal

@external
def modify_nested_struct(_human: Human) -> Human:
    human: Human = _human

    # do stuff, edit the structs
    # (13 is the length of the result)
    human.animal.fur = slice(concat(human.animal.fur, " is great"), 0, 13)

    return human
    """
    c = get_contract(code)
    addr1 = "0x1234567890123456789012345678901234567890"
    addr2 = "0x1234567890123456789012345678900000000000"
    # assert c.modify_nested_tuple([addr1, 123], [addr2, 456]) == [[addr1, 124], [addr2, 457]]
    assert c.modify_nested_struct(
        {"location": addr1, "animal": {"location": addr2, "fur": "wool"}}
    ) == (addr1, (addr2, "wool is great"))


def test_nested_single_struct(get_contract):
    code = """
struct Animal:
    fur: String[32]

struct Human:
    animal: Animal

@external
def modify_nested_single_struct(_human: Human) -> Human:
    human: Human = _human

    # do stuff, edit the structs
    # (13 is the length of the result)
    human.animal.fur = slice(concat(human.animal.fur, " is great"), 0, 13)

    return human
    """
    c = get_contract(code)

    assert c.modify_nested_single_struct({"animal": {"fur": "wool"}}) == (("wool is great",),)


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_struct(get_contract, string):
    code = f"""
struct Person:
    name: String[6]
    age: uint256

@external
def test_return() -> Person:
    return Person({{ name:"{string}", age:42 }})
    """
    c1 = get_contract(code)

    code = """
struct Person:
    name: String[6]
    age: uint256

interface jsonabi:
    def test_return() -> Person: view

@external
def test_values(a: address) -> Person:
    return jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == (string, 42)


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_single_struct(get_contract, string):
    code = f"""
struct Person:
    name: String[6]

@external
def test_return() -> Person:
    return Person({{ name:"{string}"}})
    """
    c1 = get_contract(code)

    code = """
struct Person:
    name: String[6]

interface jsonabi:
    def test_return() -> Person: view

@external
def test_values(a: address) -> Person:
    return jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == (string,)
