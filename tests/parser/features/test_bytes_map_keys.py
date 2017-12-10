import pytest
from viper.exceptions import TypeMismatchException


def test_basic_bytes_keys(get_contract):
    code = """
mapped_bytes: num[bytes <= 5]

@public
def set(k: bytes <= 5, v: num):
    self.mapped_bytes[k] = v

@public
def get(k: bytes <= 5) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set("test", 54321)

    assert c.get("test") == 54321


def test_basic_bytes_literal_key(get_contract):
    code = """
mapped_bytes: num[bytes <= 5]

@public
def set(v: num):
    self.mapped_bytes["test"] = v

@public
def get(k: bytes <= 5) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set(54321)

    assert c.get("test") == 54321


def test_basic_long_bytes_as_keys(get_contract):
    code = """
mapped_bytes: num[bytes <= 34]

@public
def set(k: bytes <= 34, v: num):
    self.mapped_bytes[k] = v

@public
def get(k: bytes <= 34) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set("a" * 34, 6789)

    assert c.get("a" * 34) == 6789


def test_basic_very_long_bytes_as_keys(get_contract):
    code = """
mapped_bytes: num[bytes <= 4096]

@public
def set(k: bytes <= 4096, v: num):
    self.mapped_bytes[k] = v

@public
def get(k: bytes <= 4096) -> num:
    return self.mapped_bytes[k]
    """

    c = get_contract(code)

    c.set("test" * 1024, 6789)

    assert c.get("test" * 1024) == 6789


def test_mismatched_byte_length(get_contract):
    code = """
mapped_bytes: num[bytes <= 34]

@public
def set(k: bytes <= 35, v: num):
    self.mapped_bytes[k] = v
    """

    with pytest.raises(TypeMismatchException):
        get_contract(code)
