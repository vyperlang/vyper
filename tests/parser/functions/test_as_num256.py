def test_convert_to_num256_with_negative_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num256:
    return convert(1-2, 'num256')
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_convert_to_num256_with_negative_input(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num) -> num256:
    return convert(x, 'num256')
"""
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(-1))


def test_convert_to_num256_with_bytes32(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num256:
    return convert(convert(-1, 'bytes32'), 'num256')
"""

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 2 ** 256 - 1
