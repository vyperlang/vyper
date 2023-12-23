def test_extract32_extraction(tx_failed, get_contract_with_gas_estimation):
    extract32_code = """
y: Bytes[100]
@external
def extrakt32(inp: Bytes[100], index: uint256) -> bytes32:
    return extract32(inp, index)

@external
def extrakt32_mem(inp: Bytes[100], index: uint256) -> bytes32:
    x: Bytes[100] = inp
    return extract32(x, index)

@external
def extrakt32_storage(index: uint256, inp: Bytes[100]) -> bytes32:
    self.y = inp
    return extract32(self.y, index)
    """

    c = get_contract_with_gas_estimation(extract32_code)
    test_cases = (
        (b"c" * 31, 0),
        (b"c" * 32, 0),
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
        if 0 <= i <= len(S) - 32:
            expected_result = S[i : i + 32]
            assert c.extrakt32(S, i) == expected_result
            assert c.extrakt32_mem(S, i) == expected_result
            assert c.extrakt32_storage(i, S) == expected_result
        else:
            with tx_failed():
                c.extrakt32(S, i)

    print("Passed bytes32 extraction test")


def test_extract32_code(tx_failed, get_contract_with_gas_estimation):
    extract32_code = """
@external
def foo(inp: Bytes[32]) -> int128:
    return extract32(inp, 0, output_type=int128)

@external
def bar(inp: Bytes[32]) -> uint256:
    return extract32(inp, 0, output_type=uint256)

@external
def baz(inp: Bytes[32]) -> bytes32:
    return extract32(inp, 0, output_type=bytes32)

@external
def fop(inp: Bytes[32]) -> bytes32:
    return extract32(inp, 0)

@external
def foq(inp: Bytes[32]) -> address:
    return extract32(inp, 0, output_type=address)
    """

    c = get_contract_with_gas_estimation(extract32_code)
    assert c.foo(b"\x00" * 30 + b"\x01\x01") == 257
    assert c.bar(b"\x00" * 30 + b"\x01\x01") == 257

    with tx_failed():
        c.foo(b"\x80" + b"\x00" * 30)

    assert c.bar(b"\x80" + b"\x00" * 31) == 2**255

    assert c.baz(b"crow" * 8) == b"crow" * 8
    assert c.fop(b"crow" * 8) == b"crow" * 8
    assert c.foq(b"\x00" * 12 + b"3" * 20) == "0x" + "3" * 40

    with tx_failed():
        c.foq(b"crow" * 8)

    print("Passed extract32 test")
