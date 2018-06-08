

def test_convert_bytes32_to_num_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: int128 = convert(y, 'int128')
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_convert_address_to_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
    x: int128 = convert(msg.sender, 'int128')
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_out_of_range(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
    x: int128
    x = convert(340282366920938463463374607431768211459, 'int128')
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)
