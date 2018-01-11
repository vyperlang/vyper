def test_as_num256_with_negative_num(assert_compile_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num256:
    return as_num256(1-2)
"""
    assert_compile_failed(lambda: get_contract_with_gas_estimation(code), Exception)


def test_as_num256_with_negative_input(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
@public
def foo(x: num) -> num256:
    return as_num256(x)
"""
    c = get_contract_with_gas_estimation(code)
    assert_tx_failed(lambda: c.foo(-1))


def test_as_num256_with_bytes32(get_contract_with_gas_estimation):
    code = """
@public
def foo() -> num256:
    return as_num256(as_bytes32(-1))
"""

    c = get_contract_with_gas_estimation(code)
    assert c.foo() == 2 ** 256 - 1
