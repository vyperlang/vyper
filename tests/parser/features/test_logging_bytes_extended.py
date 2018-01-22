

def test_bytes_logging_extended(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: num, arg2: bytes <= 64, arg3: num})

@public
def foo():
    log.MyLog(667788, 'hellohellohellohellohellohellohellohellohello', 334455)
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == 667788
    assert log[0]['arg2'] == b"hello" * 9
    assert log[0]['arg3'] == 334455


def test_bytes_logging_extended_variables(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: bytes <= 64, arg2: bytes <= 64, arg3: bytes <= 64})

@public
def foo():
    a: bytes <= 64 = 'hellohellohellohellohellohellohellohellohello'
    b: bytes <= 64 = 'hellohellohellohellohellohellohellohello'
    c: bytes <= 64 = 'hellohellohellohellohellohellohello'
    log.MyLog(a, b, c)
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == b"hello" * 9
    assert log[0]['arg2'] == b"hello" * 8
    assert log[0]['arg3'] == b"hello" * 7


def test_bytes_logging_extended_passthrough(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: num, arg2: bytes <= 64, arg3: num})

@public
def foo(a: num, b: bytes <= 64, c: num):
    log.MyLog(a, b, c)
    """

    c = get_contract_with_gas_estimation(code)
    c.foo(333, b"flower" * 8, 444)
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == 333
    assert log[0]['arg2'] == b"flower" * 8
    assert log[0]['arg3'] == 444


def test_bytes_logging_extended_storage(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({arg1: num, arg2: bytes <= 64, arg3: num})
a: num
b: bytes <= 64
c: num

@public
def foo():
    log.MyLog(self.a, self.b, self.c)

@public
def set(x: num, y: bytes <= 64, z: num):
    self.a = x
    self.b = y
    self.c = z
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == 0
    assert log[0]['arg2'] == b""
    assert log[0]['arg3'] == 0

    c.set(333, b"flower" * 8, 444)
    c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == 333
    assert log[0]['arg2'] == b"flower" * 8
    assert log[0]['arg3'] == 444


def test_bytes_logging_extended_mixed_with_lists(t, get_contract_with_gas_estimation, get_logs, chain):
    code = """
MyLog: __log__({
    arg1: num[2][2],
    arg2: bytes <= 64,
    arg3: num,
    arg4: bytes <= 64
})

@public
def foo():
    log.MyLog(
        [[24, 26], [12, 10]],
        'hellohellohellohellohellohellohellohellohello',
        314159,
        'helphelphelphelphelphelphelphelphelphelphelp',
    )
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()
    receipt = chain.head_state.receipts[-1]
    log = get_logs(receipt, c)
    assert log[0]['arg1'] == [[24, 26], [12, 10]]
    assert log[0]['arg2'] == b"hello" * 9
    assert log[0]['arg3'] == 314159
    assert log[0]['arg4'] == b"help" * 11
