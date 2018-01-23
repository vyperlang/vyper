

def test_as_num128_bytes32_overflow(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def test1():
    y: bytes32 = 0x1000000000000000000000000000000000000000000000000000000000000000
    x: num = as_num128(y)
    """

    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.test1())


def test_as_num128_address(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def test2():
  x: num = as_num128(msg.sender)
    """

    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)
