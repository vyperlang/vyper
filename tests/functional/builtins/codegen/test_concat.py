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


def test_concat_buffer(get_contract):
    # GHSA-2q8v-3gqq-4f8p
    code = """
@internal
def bar() -> uint256:
    sss: String[2] = concat("a", "b")
    return 1


@external
def foo() -> int256:
    a: int256 = -1
    b: uint256 = self.bar()
    return a
    """
    c = get_contract(code)
    assert c.foo() == -1


def test_concat_buffer2(get_contract):
    # GHSA-2q8v-3gqq-4f8p
    code = """
i: immutable(int256)

@deploy
def __init__():
    i = -1
    s: String[2] = concat("a", "b")

@external
def foo() -> int256:
    return i
    """
    c = get_contract(code)
    assert c.foo() == -1


def test_concat_buffer3(get_contract):
    # GHSA-2q8v-3gqq-4f8p
    code = """
s: String[1]
s2: String[33]
s3: String[34]

@deploy
def __init__():
    self.s = "a"
    self.s2 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" # 33*'a'

@internal
def bar() -> uint256:
    self.s3 = concat(self.s, self.s2)
    return 1

@external
def foo() -> int256:
    i: int256 = -1
    b: uint256 = self.bar()
    return i
    """
    c = get_contract(code)
    assert c.foo() == -1


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


def test_small_bytes(get_contract_with_gas_estimation):
    # TODO maybe use parametrization or hypothesis for the examples
    code = """
@external
def small_bytes1(a: bytes1, b: Bytes[2]) -> Bytes[3]:
    return concat(a, b)

@external
def small_bytes2(a: Bytes[1], b: bytes2) -> Bytes[3]:
    return concat(a, b)

@external
def small_bytes3(a: bytes4, b: bytes32) -> Bytes[36]:
    return concat(a, b)

@external
def small_bytes4(a: bytes8, b: Bytes[32], c: bytes8) -> Bytes[48]:
    return concat(a, b, c)
    """
    contract = get_contract_with_gas_estimation(code)

    i = 0

    def bytes_for_len(n):
        nonlocal i
        # bytes constructor with state
        # (so we don't keep generating the same string)
        xs = []
        for _ in range(n):
            i += 1
            i %= 256
            xs.append(i)
        return bytes(xs)

    a, b = bytes_for_len(1), bytes_for_len(2)
    assert contract.small_bytes1(a, b) == a + b

    a, b = bytes_for_len(1), bytes_for_len(1)
    assert contract.small_bytes1(a, b) == a + b

    a, b = bytes_for_len(1), bytes_for_len(2)
    assert contract.small_bytes2(a, b) == a + b

    a, b = b"", bytes_for_len(2)
    assert contract.small_bytes2(a, b) == a + b

    a, b = bytes_for_len(4), bytes_for_len(32)
    assert contract.small_bytes3(a, b) == a + b

    a, b, c = bytes_for_len(8), bytes_for_len(32), bytes_for_len(8)
    assert contract.small_bytes4(a, b, c) == a + b + c

    a, b, c = bytes_for_len(8), bytes_for_len(1), bytes_for_len(8)
    assert contract.small_bytes4(a, b, c) == a + b + c

    a, b, c = bytes_for_len(8), bytes_for_len(0), bytes_for_len(8)
    assert contract.small_bytes4(a, b, c) == a + b + c
