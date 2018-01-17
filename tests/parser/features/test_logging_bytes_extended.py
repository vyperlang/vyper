

def test_bytes_logging_extended(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: num, arg2: bytes <= 64, arg3: num})

@public
def foo() -> bytes <= 256:
    log.MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    return "hello"
    """

    c = get_contract_with_gas_estimation(code)
    a = c.foo()
    import ipdb; ipdb.set_trace()
    # receipt = chain.head_state.receipts[-1]
    # print(receipt, c))
