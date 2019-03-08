
def test_convert_from_bytes32(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    test_bytes = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xF5\xD4\x02\x0d\xCA\x6a\x62\xbB\x1e\xfF\xcC\x92\x12\xAA\xF3\xc9\x81\x9E\x30\xD7"  # noqa: E501

    test_bytes_to_address = """
@public
def test_bytes_to_address(x: bytes32) -> address:
    return convert(x, address)
    """

    c = get_contract_with_gas_estimation(test_bytes_to_address)
    assert c.test_bytes_to_address(test_bytes) == test_address
