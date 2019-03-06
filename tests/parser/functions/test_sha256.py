import hashlib


def test_sha256_literal(get_contract):
    code = """
@public
def bar() -> bytes32:
    return sha256("test")
    """

    c = get_contract(code)

    assert c.bar() == hashlib.sha256(b"test").digest()


def test_sha256_bytes32(get_contract):
    code = """
@public
def bar(a: bytes32) -> bytes32:
    return sha256(a)
    """

    c = get_contract(code)

    test_val = 8 * b"bBaA"
    assert c.bar(test_val) == hashlib.sha256(test_val).digest()


def test_sha256_bytearraylike(get_contract):
    code = """
@public
def bar(a: string[100]) -> bytes32:
    return sha256(a)
    """

    c = get_contract(code)

    test_val = "test me! test me!"
    assert c.bar(test_val) == hashlib.sha256(test_val.encode()).digest()
    test_val = "fun"
    assert c.bar(test_val) == hashlib.sha256(test_val.encode()).digest()


def test_sha256_bytearraylike_storage(get_contract):
    code = """
a: public(bytes[100])

@public
def set(b: bytes[100]):
    self.a = b

@public
def bar() -> bytes32:
    return sha256(self.a)
    """

    c = get_contract(code)

    test_val = b"test me! test me!"
    c.set(test_val, transact={})
    assert c.a() == test_val
    assert c.bar() == hashlib.sha256(test_val).digest()
