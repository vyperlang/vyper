from ethereum.tools import tester


def test_extract32_extraction(get_contract_with_gas_estimation):
    extract32_code = """
y: bytes <= 100
@public
def extrakt32(inp: bytes <= 100, index: num) -> bytes32:
    return extract32(inp, index)

@public
def extrakt32_mem(inp: bytes <= 100, index: num) -> bytes32:
    x: bytes <= 100 = inp
    return extract32(x, index)

@public
def extrakt32_storage(index: num, inp: bytes <= 100) -> bytes32:
    self.y = inp
    return extract32(self.y, index)
    """

    c = get_contract_with_gas_estimation(extract32_code)
    test_cases = (
        (b"c" * 31, 0),
        (b"c" * 32, 0),
        (b"c" * 32, -1),
        (b"c" * 33, 0),
        (b"c" * 33, 1),
        (b"c" * 33, 2),
        (b"cow" * 30, 0),
        (b"cow" * 30, 1),
        (b"cow" * 30, 31),
        (b"cow" * 30, 32),
        (b"cow" * 30, 33),
        (b"cow" * 30, 34),
        (b"cow" * 30, 58),
        (b"cow" * 30, 59),
    )

    for S, i in test_cases:
        expected_result = S[i: i + 32] if 0 <= i <= len(S) - 32 else None
        if expected_result is None:
            try:
                c.extrakt32(S, i)
                success = True
            except tester.TransactionFailed:
                success = False
            assert not success
        else:
            assert c.extrakt32(S, i) == expected_result
            assert c.extrakt32_mem(S, i) == expected_result
            assert c.extrakt32_storage(i, S) == expected_result

    print("Passed bytes32 extraction test")


def test_extract32_code(get_contract_with_gas_estimation):
    extract32_code = """
@public
def foo(inp: bytes <= 32) -> num:
    return extract32(inp, 0, type=num128)

@public
def bar(inp: bytes <= 32) -> num256:
    return extract32(inp, 0, type=num256)

@public
def baz(inp: bytes <= 32) -> bytes32:
    return extract32(inp, 0, type=bytes32)

@public
def fop(inp: bytes <= 32) -> bytes32:
    return extract32(inp, 0)

@public
def foq(inp: bytes <= 32) -> address:
    return extract32(inp, 0, type=address)
    """

    c = get_contract_with_gas_estimation(extract32_code)
    assert c.foo(b"\x00" * 30 + b"\x01\x01") == 257
    assert c.bar(b"\x00" * 30 + b"\x01\x01") == 257
    try:
        c.foo(b"\x80" + b"\x00" * 30)
        success = True
    except tester.TransactionFailed:
        success = False
    assert not success
    assert c.bar(b"\x80" + b"\x00" * 31) == 2**255

    assert c.baz(b"crow" * 8) == b"crow" * 8
    assert c.fop(b"crow" * 8) == b"crow" * 8
    assert c.foq(b"\x00" * 12 + b"3" * 20) == "0x" + "3" * 40
    try:
        c.foq(b"crow" * 8)
        success = True
    except tester.TransactionFailed:
        success = False
    assert not success

    print('Passed extract32 test')
