
def test_log_dynamic_static_combo(get_logs, get_contract_with_gas_estimation, w3):
    code = """
TestLog: event({testData1: bytes32,testData2: bytes[60], testData3: bytes[8]})

@private
@constant
def to_bytes(value: uint256) -> bytes[8]:
    return slice(concat(b"", convert(value, bytes32)), start=24, len=8)

@private
@constant
def to_bytes32(value: uint256) -> bytes32:
    return convert(value, bytes32)

@public
def test_func(value: uint256):
    data2: bytes[60] = concat(self.to_bytes32(value),self.to_bytes(value),b"testing")
    log.TestLog(self.to_bytes32(value), data2, self.to_bytes(value))

    loggedValue: bytes32 = self.to_bytes32(value)
    loggedValue2: bytes[8] = self.to_bytes(value)
    log.TestLog(loggedValue, data2, loggedValue2)
    """

    c = get_contract_with_gas_estimation(code)

    tx_hash = c.test_func(123, transact={})

    logs = get_logs(tx_hash, c, 'TestLog')

    log = logs[0].args
    assert w3.toInt(log.testData1) == 123
    assert w3.toInt(log.testData2[:32]) == 123
    assert log.testData2[-7:] == b'testing'
    assert log.testData2[32:] == b'\x00\x00\x00\x00\x00\x00\x00{testing'
    assert log.testData3 == b'\x00\x00\x00\x00\x00\x00\x00{'
    assert w3.toInt(log.testData3) == 123

    assert logs[0].args == logs[1].args


def test_log_dynamic_static_combo2(get_logs, get_contract, w3):
    code = """
TestLog: event({testData1: bytes32,testData2: bytes[133], testData3: bytes[8] })

@private
@constant
def to_bytes(value: uint256) -> bytes[8]:
    return slice(concat(b"", convert(value, bytes32)), start=24, len=8)

@private
@constant
def to_bytes32(value: uint256) -> bytes32:
    return convert(value, bytes32)

@public
def test_func(value: uint256,input: bytes[133]):

    data2: bytes[200] = "hello world"

    # log.TestLog(self.to_bytes32(value),input,self.to_bytes(value))
    log.TestLog(self.to_bytes32(value),input,"bababa")
    """

    c = get_contract(code)

    # assert c.test_func(2**255, b'x' * 129, call={}) == b'x' * 129
    tx_hash = c.test_func(1234444, b'x' * 129, transact={})
    tx_receipt = w3.eth.getTransactionReceipt(tx_hash)
    print(tx_receipt)
    logs = get_logs(tx_hash, c, 'TestLog')

    print(logs[0].args)

    assert w3.toInt(logs[0].args.testData1) == 1234444
    assert logs[0].args.testData3 == b"bababa"
    assert logs[0].args.testData2 == b'x' * 129


def test_log_single_function_call(get_logs, get_contract, w3):
    code = """
TestLog: event({testData1: bytes32, testData2: bytes[133]})

@private
@constant
def to_bytes32(value: uint256) -> bytes32:
    return convert(value, bytes32)

@public
def test_func(value: uint256,input: bytes[133]):

    data2: bytes[200] = b"hello world"

    # log will be malformed
    # log.TestLog(self.to_bytes32(value),input,self.to_bytes(value))
    log.TestLog(self.to_bytes32(value), input)
    """

    c = get_contract(code)

    tx_hash = c.test_func(1234444, b'x' * 129, transact={})
    logs = get_logs(tx_hash, c, 'TestLog')

    assert w3.toInt(logs[0].args.testData1) == 1234444
    assert logs[0].args.testData2 == b'x' * 129


def test_original_problem_function(get_logs, get_contract, w3):
    # See #1205 for further details, this is kept as test case as it introduces very specific
    # edge cases to the ABI encoder when logging.
    code = """
TestLog: event({testData1: bytes32,testData2: bytes[2064], testData3: bytes[8] })

@private
@constant
def to_bytes(value: uint256) -> bytes[8]:
    return slice(concat(b"", convert(value, bytes32)), start=24, len=8)

@private
@ constant
def to_bytes32(value: uint256) -> bytes32:
    return convert(value, bytes32)

@public
def test_func(value: uint256,input: bytes[2048]):

    data2: bytes[2064] = concat(self.to_bytes(value),self.to_bytes(value),input)

    # log will be malformed
    log.TestLog(self.to_bytes32(value), data2, self.to_bytes(value))

    loggedValue: bytes[8] = self.to_bytes(value)

    # log will be normal
    log.TestLog(self.to_bytes32(value),data2,loggedValue)
    """

    c = get_contract(code)

    tx_hash = c.test_func(333, b'x' * 132, transact={})
    tx_receipt = w3.eth.getTransactionReceipt(tx_hash)
    print(tx_receipt)
    logs = get_logs(tx_hash, c, 'TestLog')

    print(logs[0].args)

    assert w3.toInt(logs[0].args.testData1) == 333

    assert w3.toInt(logs[0].args.testData2[0:8]) == 333
    assert w3.toInt(logs[0].args.testData2[8:16]) == 333
    assert logs[0].args.testData2[16:] == b'x' * 132
    assert w3.toInt(logs[0].args.testData3) == 333

    assert logs[0].args == logs[1].args
