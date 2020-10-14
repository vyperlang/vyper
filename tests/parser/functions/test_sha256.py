import hashlib

import pytest

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_sha256_string_literal(get_contract_with_gas_estimation):
    code = """
@external
def bar() -> bytes32:
    return sha256("test")
    """

    c = get_contract_with_gas_estimation(code)

    assert c.bar() == hashlib.sha256(b"test").digest()


def test_sha256_literal_bytes(get_contract_with_gas_estimation):
    code = """
@external
def bar() -> (bytes32 , bytes32):
    x: bytes32 = sha256("test")
    y: bytes32 = sha256(b"test")
    return x, y
    """
    c = get_contract_with_gas_estimation(code)
    h = hashlib.sha256(b"test").digest()
    assert c.bar() == [h, h]


def test_sha256_bytes32(get_contract_with_gas_estimation):
    code = """
@external
def bar(a: bytes32) -> bytes32:
    return sha256(a)
    """

    c = get_contract_with_gas_estimation(code)

    test_val = 8 * b"bBaA"
    assert c.bar(test_val) == hashlib.sha256(test_val).digest()


def test_sha256_bytearraylike(get_contract_with_gas_estimation):
    code = """
@external
def bar(a: String[100]) -> bytes32:
    return sha256(a)
    """

    c = get_contract_with_gas_estimation(code)

    test_val = "test me! test me!"
    assert c.bar(test_val) == hashlib.sha256(test_val.encode()).digest()
    test_val = "fun"
    assert c.bar(test_val) == hashlib.sha256(test_val.encode()).digest()


def test_sha256_bytearraylike_storage(get_contract_with_gas_estimation):
    code = """
a: public(Bytes[100])

@external
def set(b: Bytes[100]):
    self.a = b

@external
def bar() -> bytes32:
    return sha256(self.a)
    """

    c = get_contract_with_gas_estimation(code)

    test_val = b"test me! test me!"
    c.set(test_val, transact={})
    assert c.a() == test_val
    assert c.bar() == hashlib.sha256(test_val).digest()
