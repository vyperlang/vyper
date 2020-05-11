from vyper.exceptions import TypeMismatch


def test_convert_from_bool(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@public
def foo():
    bar: bool = True
    foobar: bool = convert(bar, bool)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        TypeMismatch
    )

    code = """
@public
def foo():
    foobar: bool = convert(False, bool)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        TypeMismatch
    )


def test_convert_from_decimal(get_contract_with_gas_estimation):
    code = """
bar: decimal
nar: decimal
mar: decimal

@public
def foo() -> bool:
    return convert(100.0, bool)

@public
def hoo() -> bool:
    return convert(-100.0, bool)

@public
def goo() -> bool:
    return convert(0.0, bool)

@public
def foobar() -> bool:
    self.bar = 100.0
    return convert(self.bar, bool)

@public
def hoonar() -> bool:
    self.nar = -100.0
    return convert(self.nar, bool)

@public
def goomar() -> bool:
    self.mar = 0.0
    return convert(self.mar, bool)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True
    assert c.hoo() is True
    assert c.goo() is False
    assert c.foobar() is True
    assert c.hoonar() is True
    assert c.goomar() is False


def test_convert_from_int128(get_contract_with_gas_estimation):
    code = """
@public
def foo(bar: int128) -> bool:
    foobar: bool = convert(bar, bool)
    return foobar

@public
def goo() -> bool:
    return convert(100, bool)

@public
def hoo() -> bool:
    return convert(0, bool)

@public
def joo() -> bool:
    return convert(-100, bool)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(100) is True
    assert c.foo(0) is False
    assert c.foo(-100) is True

    assert c.goo() is True
    assert c.hoo() is False
    assert c.joo() is True


def test_convert_from_uint256(get_contract_with_gas_estimation):
    code = """
@public
def foo(bar: uint256) -> bool:
    foobar: bool = convert(bar, bool)
    return foobar

@public
def goo() -> bool:
    return convert(-100, bool)

@public
def hoo() -> bool:
    return convert(100, bool)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(100) is True
    assert c.foo(0) is False

    assert c.goo() is True
    assert c.hoo() is True


def test_convert_from_bytes32(get_contract_with_gas_estimation):
    code = """
@public
def foo(bar: bytes32) -> bool:
    foobar: bool = convert(bar, bool)
    return foobar

@public
def goo() -> bool:
    return convert(0x0000000000000000000000000000000000000000000000000000000000000000, bool)

@public
def hoo() -> bool:
    return convert(0x000000000FFF0000000000000000000000000000FF0000000000000000000FFF, bool)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(b'\x0F' * 32) is True
    assert c.foo(b'\x00' * 32) is False

    assert c.goo() is False
    assert c.hoo() is True


def test_convert_from_bytes(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@public
def foo(bar: bytes[5]) -> bool:
    return convert(bar, bool)

@public
def goo(nar: bytes[32]) -> bool:
    return convert(nar, bool)
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo(b'\x00\x00\x00\x00\x00') is False
    assert c.foo(b'\x00\x07\x5B\xCD\x15') is True
    assert c.goo(b"") is False
    assert c.goo(b"\x00") is False
    assert c.goo(b"\x00" * 32) is False
    assert c.goo(b"\x01") is True
    assert c.goo(b"\x00\x01") is True
    assert c.goo(b"\x01\x00\x00\x00\x01") is True
    assert c.goo(b"\xff" * 32) is True

    code = """
@public
def foo(bar: bytes[33]) -> bool:
    return convert(bar, bool)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        TypeMismatch
    )

    code = """
@public
def foo() -> bool:
    bar: bytes[63] = "Hello darkness, my old friend I've come to talk with you again."
    return convert(bar, bool)
    """

    assert_compile_failed(
        lambda: get_contract_with_gas_estimation(code),
        TypeMismatch
    )


def test_convert_from_address(w3, get_contract_with_gas_estimation):
    code = """
@public
def test_address_to_bool(val: address) -> bool:
    temp: bool = convert(val, bool)
    return temp

@public
def test_literal_zero_address() -> bool:
    return convert(ZERO_ADDRESS, bool)

@public
def test_sender() -> bool:
    return convert(msg.sender, bool)
    """

    a = w3.eth.accounts[0]
    c = get_contract_with_gas_estimation(code)

    assert c.test_address_to_bool((b'\x00' * 19) + (b'\x01')) is True
    assert c.test_address_to_bool(a) is True
    assert c.test_address_to_bool(b'\x00' * 20) is False

    assert c.test_literal_zero_address() is False
    assert c.test_sender() is True
