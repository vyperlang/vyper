import pytest

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

