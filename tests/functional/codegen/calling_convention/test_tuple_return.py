import pytest


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_string_inside_tuple(get_contract, string):
    code = f"""
@external
def test_return() -> (String[6], uint256):
    return "{string}", 42
    """
    c1 = get_contract(code)

    code = """
interface jsonabi:
    def test_return() -> (String[6], uint256): view

@external
def test_values(a: address) -> (String[6], uint256):
    return jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == [string, 42]


@pytest.mark.parametrize("string", ["a", "abc", "abcde", "potato"])
def test_bytes_inside_tuple(get_contract, string):
    code = f"""
@external
def test_return() -> (Bytes[6], uint256):
    return b"{string}", 42
    """
    c1 = get_contract(code)

    code = """
interface jsonabi:
    def test_return() -> (Bytes[6], uint256): view

@external
def test_values(a: address) -> (Bytes[6], uint256):
    return jsonabi(a).test_return()
    """

    c2 = get_contract(code)
    assert c2.test_values(c1.address) == [bytes(string, "utf-8"), 42]
