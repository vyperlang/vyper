import pytest


def test_nested_tuple(get_contract):
    code = """
struct Animal:
    location: address
    fur: uint256

struct Human:
    location: address
    height: uint256

@external
def return_nested_tuple() -> (Animal, Human):
    animal: Animal = Animal({
        location: 0x1234567890123456789012345678901234567890,
        fur: 123
    })
    human: Human = Human({
        location: 0x1234567890123456789012345678900000000000,
        height: 456
    })

    # do stuff, edit the structs
    animal.fur += 1
    human.height += 1

    return animal, human
    """
    c = get_contract(code)
    addr1 = "0x1234567890123456789012345678901234567890"
    addr2 = "0x1234567890123456789012345678900000000000"
    assert c.return_nested_tuple() == [(addr1, 124), (addr2, 457)]


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_tuple(get_contract, string):
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
    assert c2.test_values(c1.address) == [string, 42]
