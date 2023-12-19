import pytest

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_log_dynamic_static_combo(get_logs, get_contract_with_gas_estimation, w3):
    code = """
event TestLog:
    testData1: bytes32
    testData2: Bytes[60]
    testData3: Bytes[8]

@internal
@view
def to_bytes(_value: uint256) -> Bytes[8]:
    return slice(concat(b"", convert(_value, bytes32)), 24, 8)

@internal
@view
def to_bytes32(_value: uint256) -> bytes32:
    return convert(_value, bytes32)

@external
def test_func(_value: uint256):
    data2: Bytes[60] = concat(self.to_bytes32(_value),self.to_bytes(_value),b"testing")
    log TestLog(self.to_bytes32(_value), data2, self.to_bytes(_value))

    loggedValue: bytes32 = self.to_bytes32(_value)
    loggedValue2: Bytes[8] = self.to_bytes(_value)
    log TestLog(loggedValue, data2, loggedValue2)
    """

    c = get_contract_with_gas_estimation(code)

    tx_hash = c.test_func(123, transact={})

    logs = get_logs(tx_hash, c, "TestLog")

    log = logs[0].args
    assert w3.to_int(log.testData1) == 123
    assert w3.to_int(log.testData2[:32]) == 123
    assert log.testData2[-7:] == b"testing"
    assert log.testData2[32:] == b"\x00\x00\x00\x00\x00\x00\x00{testing"
    assert log.testData3 == b"\x00\x00\x00\x00\x00\x00\x00{"
    assert w3.to_int(log.testData3) == 123

    assert logs[0].args == logs[1].args


def test_log_dynamic_static_combo2(get_logs, get_contract, w3):
    code = """
event TestLog:
    testData1: bytes32
    testData2: Bytes[133]
    testData3: String[8]

@internal
@view
def to_bytes(_value: uint256) -> Bytes[8]:
    return slice(concat(b"", convert(_value, bytes32)), 24, 8)

@internal
@view
def to_bytes32(_value: uint256) -> bytes32:
    return convert(_value, bytes32)

@external
def test_func(_value: uint256,input: Bytes[133]):

    data2: Bytes[200] = b"hello world"

    # log TestLog(self.to_bytes32(_value),input,self.to_bytes(_value))
    log TestLog(self.to_bytes32(_value),input,"bababa")
    """

    c = get_contract(code)

    # assert c.test_func(2**255, b'x' * 129, call={}) == b'x' * 129
    tx_hash = c.test_func(1234444, b"x" * 129, transact={})
    tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
    print(tx_receipt)
    logs = get_logs(tx_hash, c, "TestLog")

    print(logs[0].args)

    assert w3.to_int(logs[0].args.testData1) == 1234444
    assert logs[0].args.testData3 == "bababa"
    assert logs[0].args.testData2 == b"x" * 129


def test_log_single_function_call(get_logs, get_contract, w3):
    code = """
event TestLog:
    testData1: bytes32
    testData2: Bytes[133]

@internal
@view
def to_bytes32(_value: uint256) -> bytes32:
    return convert(_value, bytes32)

@external
def test_func(_value: uint256,input: Bytes[133]):

    data2: Bytes[200] = b"hello world"

    # log will be malformed
    # log TestLog(self.to_bytes32(_value),input,self.to_bytes(_value))
    log TestLog(self.to_bytes32(_value), input)
    """

    c = get_contract(code)

    tx_hash = c.test_func(1234444, b"x" * 129, transact={})
    logs = get_logs(tx_hash, c, "TestLog")

    assert w3.to_int(logs[0].args.testData1) == 1234444
    assert logs[0].args.testData2 == b"x" * 129


def test_original_problem_function(get_logs, get_contract, w3):
    # See #1205 for further details, this is kept as test case as it introduces very specific
    # edge cases to the ABI encoder when logging.
    code = """
event TestLog:
    testData1: bytes32
    testData2: Bytes[2064]
    testData3: Bytes[8]

@internal
@view
def to_bytes(_value: uint256) -> Bytes[8]:
    return slice(concat(b"", convert(_value, bytes32)), 24, 8)

@internal
@view
def to_bytes32(_value: uint256) -> bytes32:
    return convert(_value, bytes32)

@external
def test_func(_value: uint256,input: Bytes[2048]):

    data2: Bytes[2064] = concat(self.to_bytes(_value),self.to_bytes(_value),input)

    # log will be malformed
    log TestLog(self.to_bytes32(_value), data2, self.to_bytes(_value))

    loggedValue: Bytes[8] = self.to_bytes(_value)

    # log will be normal
    log TestLog(self.to_bytes32(_value),data2,loggedValue)
    """

    c = get_contract(code)

    tx_hash = c.test_func(333, b"x" * 132, transact={})
    tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
    print(tx_receipt)
    logs = get_logs(tx_hash, c, "TestLog")

    print(logs[0].args)

    assert w3.to_int(logs[0].args.testData1) == 333

    assert w3.to_int(logs[0].args.testData2[0:8]) == 333
    assert w3.to_int(logs[0].args.testData2[8:16]) == 333
    assert logs[0].args.testData2[16:] == b"x" * 132
    assert w3.to_int(logs[0].args.testData3) == 333

    assert logs[0].args == logs[1].args
