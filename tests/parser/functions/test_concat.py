from vyper.exceptions import TypeMismatch


def test_concat(get_contract_with_gas_estimation):
    test_concat = """
@external
def foo2(input1: Bytes[50], input2: Bytes[50]) -> Bytes[1000]:
    return concat(input1, input2)

@external
def foo3(input1: Bytes[50], input2: Bytes[50], input3: Bytes[50]) -> Bytes[1000]:
    return concat(input1, input2, input3)
    """

    c = get_contract_with_gas_estimation(test_concat)
    assert c.foo2(b"h", b"orse") == b"horse"
    assert c.foo2(b"h", b"") == b"h"
    assert c.foo2(b"", b"") == b""
    assert c.foo2(b"", b"orse") == b"orse"
    assert c.foo3(b"Buffalo", b" ", b"buffalo") == b"Buffalo buffalo"
    assert c.foo2(b"\x36", b"\x35" * 32) == b"\x36" + b"\x35" * 32
    assert c.foo2(b"\x36" * 48, b"\x35" * 32) == b"\x36" * 48 + b"\x35" * 32
    assert (
        c.foo3(b"horses" * 4, b"mice" * 7, b"crows" * 10)
        == b"horses" * 4 + b"mice" * 7 + b"crows" * 10
    )  # noqa: E501
    print("Passed simple concat test")


def test_concat2(get_contract_with_gas_estimation):
    test_concat2 = """
@external
def foo(inp: Bytes[50]) -> Bytes[1000]:
    x: Bytes[50] = inp
    return concat(x, inp, x, inp, x, inp, x, inp, x, inp)
    """

    c = get_contract_with_gas_estimation(test_concat2)
    assert c.foo(b"horse" * 9 + b"vyper") == (b"horse" * 9 + b"vyper") * 10
    print("Passed second concat test")


def test_crazy_concat_code(get_contract_with_gas_estimation):
    crazy_concat_code = """
y: Bytes[10]

@external
def krazykonkat(z: Bytes[10]) -> Bytes[25]:
    x: Bytes[3] = b"cow"
    self.y = b"horse"
    return concat(x, b" ", self.y, b" ", z)
    """

    c = get_contract_with_gas_estimation(crazy_concat_code)

    assert c.krazykonkat(b"moose") == b"cow horse moose"

    print("Passed third concat test")


def test_concat_bytes32(get_contract_with_gas_estimation):
    test_concat_bytes32 = """
@external
def sandwich(inp: Bytes[100], inp2: bytes32) -> Bytes[164]:
    return concat(inp2, inp, inp2)

@external
def fivetimes(inp: bytes32) -> Bytes[160]:
    return concat(inp, inp, inp, inp, inp)
    """

    c = get_contract_with_gas_estimation(test_concat_bytes32)
    assert c.sandwich(b"cow", b"\x35" * 32) == b"\x35" * 32 + b"cow" + b"\x35" * 32, c.sandwich(
        b"cow", b"\x35" * 32
    )  # noqa: E501
    assert c.sandwich(b"", b"\x46" * 32) == b"\x46" * 64
    assert c.sandwich(b"\x57" * 95, b"\x57" * 32) == b"\x57" * 159
    assert c.sandwich(b"\x57" * 96, b"\x57" * 32) == b"\x57" * 160
    assert c.sandwich(b"\x57" * 97, b"\x57" * 32) == b"\x57" * 161
    assert c.fivetimes(b"mongoose" * 4) == b"mongoose" * 20

    print("Passed concat bytes32 test")


def test_konkat_code(get_contract_with_gas_estimation):
    konkat_code = """
ecks: bytes32

@external
def foo(x: bytes32, y: bytes32) -> Bytes[64]:
    self.ecks = x
    return concat(self.ecks, y)

@external
def goo(x: bytes32, y: bytes32) -> Bytes[64]:
    self.ecks = x
    return concat(self.ecks, y)

@external
def hoo(x: bytes32, y: bytes32) -> Bytes[64]:
    return concat(x, y)
    """

    c = get_contract_with_gas_estimation(konkat_code)
    assert c.foo(b"\x35" * 32, b"\x00" * 32) == b"\x35" * 32 + b"\x00" * 32
    assert c.goo(b"\x35" * 32, b"\x00" * 32) == b"\x35" * 32 + b"\x00" * 32
    assert c.hoo(b"\x35" * 32, b"\x00" * 32) == b"\x35" * 32 + b"\x00" * 32

    print("Passed second concat tests")


def test_small_output(get_contract_with_gas_estimation):
    code = """
@external
def small_output(a: String[5], b: String[4]) -> String[9]:
    c: String[9] = concat(a, b)
    return c
    """
    c = get_contract_with_gas_estimation(code)
    assert c.small_output("abcde", "fghi") == "abcdefghi"
    assert c.small_output("", "") == ""


def test_large_output(get_contract_with_gas_estimation, assert_compile_failed):
    code = """
@external
def large_output(a: String[33], b: String[33]) -> String[64]:
    c: String[64] = concat(a, b)
    return c
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatch)
