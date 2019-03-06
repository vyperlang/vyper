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
