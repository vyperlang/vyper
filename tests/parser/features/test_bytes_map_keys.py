import pytest
from vyper.exceptions import TypeMismatchException


def test_basic_bytes_keys(w3, get_contract):
    code = """
mapped_bytes: int128[bytes[5]]

@public
def set(k: bytes[5], v: int128):
    self.mapped_bytes[k] = v

@public
def get(k: bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"test", 54321, transact={})

    assert c.get(b"test") == 54321


def test_basic_bytes_literal_key(get_contract):
    code = """
mapped_bytes: int128[bytes[5]]

@public
def set(v: int128):
    self.mapped_bytes["test"] = v

@public
def get(k: bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(54321, transact={})

    assert c.get(b"test") == 54321


def test_basic_long_bytes_as_keys(get_contract):
    code = """
mapped_bytes: int128[bytes[34]]

@public
def set(k: bytes[34], v: int128):
    self.mapped_bytes[k] = v

@public
def get(k: bytes[34]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, transact={'gas': 10**6})

    assert c.get(b"a" * 34) == 6789


def test_mismatched_byte_length(get_contract):
    code = """
mapped_bytes: int128[bytes[34]]

@public
def set(k: bytes[35], v: int128):
    self.mapped_bytes[k] = v
    """

    with pytest.raises(TypeMismatchException):
        get_contract(code)


def test_extended_bytes_key_from_storage(get_contract):
    code = """
a: int128[bytes[100000]]

@public
def __init__():
    self.a["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] = 1069

@public
def get_it1() -> int128:
    key: bytes[100000] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    return self.a[key]

@public
def get_it2() -> int128:
    return self.a["aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]

@public
def get_it3(key: bytes[100000]) -> int128:
    return self.a[key]
    """

    c = get_contract(code)

    assert c.get_it2() == 1069
    assert c.get_it2() == 1069
    assert c.get_it3(b"a" * 33) == 1069
    assert c.get_it3(b"test") == 0
