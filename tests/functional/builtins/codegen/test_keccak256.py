from vyper.utils import hex_to_int


def test_hash_code(get_contract_with_gas_estimation, keccak):
    hash_code = """
@external
def foo(inp: Bytes[100]) -> bytes32:
    return keccak256(inp)

@external
def foob() -> bytes32:
    return keccak256(b"inp")

@external
def bar() -> bytes32:
    return keccak256("inp")
    """

    c = get_contract_with_gas_estimation(hash_code)
    for inp in (b"", b"cow", b"s" * 31, b"\xff" * 32, b"\n" * 33, b"g" * 64, b"h" * 65):
        assert "0x" + c.foo(inp).hex() == keccak(inp).hex()

    assert "0x" + c.bar().hex() == keccak(b"inp").hex()
    assert "0x" + c.foob().hex() == keccak(b"inp").hex()


def test_hash_code2(get_contract_with_gas_estimation):
    hash_code2 = """
@external
def foo(inp: Bytes[100]) -> bool:
    return keccak256(inp) == keccak256("badminton")
    """
    c = get_contract_with_gas_estimation(hash_code2)
    assert c.foo(b"badminto") is False
    assert c.foo(b"badminton") is True


def test_hash_code3(get_contract_with_gas_estimation):
    hash_code3 = """
test: Bytes[100]

@external
def set_test(inp: Bytes[100]):
    self.test = inp

@external
def tryy(inp: Bytes[100]) -> bool:
    return keccak256(inp) == keccak256(self.test)

@external
def tryy_str(inp: String[100]) -> bool:
    return keccak256(inp) == keccak256(self.test)

@external
def trymem(inp: Bytes[100]) -> bool:
    x: Bytes[100] = self.test
    return keccak256(inp) == keccak256(x)

@external
def try32(inp: bytes32) -> bool:
    return keccak256(inp) == keccak256(self.test)

    """
    c = get_contract_with_gas_estimation(hash_code3)
    c.set_test(b"", transact={})
    assert c.tryy(b"") is True
    assert c.tryy_str("") is True
    assert c.trymem(b"") is True
    assert c.tryy(b"cow") is False
    c.set_test(b"cow", transact={})
    assert c.tryy(b"") is False
    assert c.tryy(b"cow") is True
    assert c.tryy_str("cow") is True
    c.set_test(b"\x35" * 32, transact={})
    assert c.tryy(b"\x35" * 32) is True
    assert c.trymem(b"\x35" * 32) is True
    assert c.try32(b"\x35" * 32) is True
    assert c.tryy(b"\x35" * 33) is False
    c.set_test(b"\x35" * 33, transact={})
    assert c.tryy(b"\x35" * 32) is False
    assert c.trymem(b"\x35" * 32) is False
    assert c.try32(b"\x35" * 32) is False
    assert c.tryy(b"\x35" * 33) is True

    print("Passed KECCAK256 hash test")


def test_hash_constant_bytes32(get_contract_with_gas_estimation, keccak):
    hex_val = "0x1234567890123456789012345678901234567890123456789012345678901234"
    code = f"""
FOO: constant(bytes32) = {hex_val}
BAR: constant(bytes32) = keccak256(FOO)
@external
def foo() -> bytes32:
    x: bytes32 = BAR
    return x
    """
    c = get_contract_with_gas_estimation(code)
    assert "0x" + c.foo().hex() == keccak(hex_to_int(hex_val).to_bytes(32, "big")).hex()


def test_hash_constant_string(get_contract_with_gas_estimation, keccak):
    str_val = "0x1234567890123456789012345678901234567890123456789012345678901234"
    code = f"""
FOO: constant(String[66]) = "{str_val}"
BAR: constant(bytes32) = keccak256(FOO)
@external
def foo() -> bytes32:
    x: bytes32 = BAR
    return x
    """
    c = get_contract_with_gas_estimation(code)
    assert "0x" + c.foo().hex() == keccak(str_val.encode()).hex()
