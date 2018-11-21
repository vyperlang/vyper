
def test_convert_from_bool(get_contract_with_gas_estimation):
    exp_code = """
@public
def testConvertBytes32(flag: bool) -> bytes32:
    flagBytes: bytes32 = convert(flag, bytes32)
    return flagBytes
    """

    c = get_contract_with_gas_estimation(exp_code)
    falseBytes = c.testConvertBytes32(False)
    assert falseBytes[31:32] == b'\x00'
    assert len(falseBytes) == 32

    trueBytes = c.testConvertBytes32(True)
    assert trueBytes[31:32] == b'\x01'
    assert len(trueBytes) == 32
