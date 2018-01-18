

def test_bytes_logging_extended(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: num, arg2: bytes <= 64, arg3: num})

@public
def foo():
    log.MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    """

    c = get_contract_with_gas_estimation(code)
    a = c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == 667788
    assert log[0]['arg2'] == b"hello" * 9
    assert log[0]['arg3'] == 334455
