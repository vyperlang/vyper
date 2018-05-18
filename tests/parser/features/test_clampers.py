def test_clamper_test_code(assert_tx_failed, get_contract_with_gas_estimation):
    clamper_test_code = """
@public
def foo(s: bytes[3]) -> bytes[3]:
    return s
    """

    c = get_contract_with_gas_estimation(clamper_test_code)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    assert_tx_failed(lambda: c.foo(b"cate"))

    print("Passed bytearray clamping test")
