import pytest

from vyper.exceptions import TypeMismatch


def test_basic_bytes_keys(w3, get_contract):
    code = """
mapped_bytes: HashMap[Bytes[5], int128]

@external
def set(k: Bytes[5], v: int128):
    self.mapped_bytes[k] = v

@external
def get(k: Bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"test", 54321, transact={})

    assert c.get(b"test") == 54321


def test_basic_bytes_literal_key(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[5], int128]

@external
def set(v: int128):
    self.mapped_bytes[b"test"] = v

@external
def get(k: Bytes[5]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(54321, transact={})

    assert c.get(b"test") == 54321


def test_basic_long_bytes_as_keys(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[34], int128]

@external
def set(k: Bytes[34], v: int128):
    self.mapped_bytes[k] = v

@external
def get(k: Bytes[34]) -> int128:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(b"a" * 34, 6789, transact={"gas": 10 ** 6})

    assert c.get(b"a" * 34) == 6789


def test_mismatched_byte_length(get_contract):
    code = """
mapped_bytes: HashMap[Bytes[34], int128]

@external
def set(k: Bytes[35], v: int128):
    self.mapped_bytes[k] = v
    """

    with pytest.raises(TypeMismatch):
        get_contract(code)


def test_extended_bytes_key_from_storage(get_contract):
    code = """
a: HashMap[Bytes[100000], int128]

@external
def __init__():
    self.a[b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"] = 1069

@external
def get_it1() -> int128:
    key: Bytes[100000] = b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    return self.a[key]

@external
def get_it2() -> int128:
    return self.a[b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]

@external
def get_it3(key: Bytes[100000]) -> int128:
    return self.a[key]
    """

    c = get_contract(code)

    assert c.get_it2() == 1069
    assert c.get_it2() == 1069
    assert c.get_it3(b"a" * 33) == 1069
    assert c.get_it3(b"test") == 0
