from vyper.utils import checksum_encode


def test_convert_from_bytes32(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    # left padded with zeroes
    test_bytes = int(test_address, 16).to_bytes(20, "big").rjust(32, b"\00")

    test_bytes_to_address = """
@external
def test_bytes_to_address(x: bytes32) -> address:
    return convert(x, address)
    """

    c = get_contract_with_gas_estimation(test_bytes_to_address)
    assert c.test_bytes_to_address(test_bytes) == test_address


def test_bytes32_clamping(get_contract, assert_tx_failed):
    test_passing = (b"\xff" * 20).rjust(32, b"\x00")
    test_fails = (b"\x01" + b"\xff" * 20).rjust(32, b"\x00")

    test_bytes_to_address = """
@external
def foo(x: bytes32) -> address:
    return convert(x, address)
    """

    c = get_contract(test_bytes_to_address)

    assert_tx_failed(lambda: c.foo(test_fails))
    assert c.foo(test_passing) == checksum_encode("0x" + "ff" * 20)


def test_convert_from_uint256(get_contract_with_gas_estimation):
    test_address = "0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7"
    test_int = int(test_address, 16)

    test_bytes_to_address = """
@external
def foo(x: uint256) -> address:
    return convert(x, address)
    """

    c = get_contract_with_gas_estimation(test_bytes_to_address)
    assert c.foo(test_int) == test_address


def test_uint256_clamping(get_contract, assert_tx_failed):
    test_fails = 2 ** 160
    test_passing = test_fails - 1

    test_bytes_to_address = """
@external
def foo(x: uint256) -> address:
    return convert(x, address)
    """

    c = get_contract(test_bytes_to_address)

    assert_tx_failed(lambda: c.foo(test_fails))
    assert c.foo(test_passing) == checksum_encode("0x" + "ff" * 20)
