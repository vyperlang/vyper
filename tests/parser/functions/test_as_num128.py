

def test_convert_bytes32_to_num_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: num = convert(y, 'num')
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_convert_address_to_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
  x: num = convert(msg.sender, 'num')
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)
