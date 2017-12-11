def test_clamper_test_code(t, get_contract_with_gas_estimation):
    clamper_test_code = """
@public
def foo(s: bytes <= 3) -> bytes <= 3:
    return s
    """

    c = get_contract_with_gas_estimation(clamper_test_code, value=1)
    assert c.foo(b"ca") == b"ca"
    assert c.foo(b"cat") == b"cat"
    try:
        c.foo(b"cate")
        success = True
    except t.TransactionFailed:
        success = False
    assert not success

    print("Passed bytearray clamping test")
