from decimal import Decimal

from vyper.exceptions import TypeMismatchException, EventDeclarationException


def test_empty_event_logging(w3, tester, keccak, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({})

@public
def foo():
    log.MyLog()
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog()', 'utf-8'))

    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'name': 'MyLog', 'inputs': [], 'anonymous': False, 'type': 'event'}
    # Event is decoded correctly
    assert hasattr(c._classic_contract.events, 'MyLog')


def test_event_logging_with_topics(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[3])})

@public
def foo():
    log.MyLog('bar')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    event_id = keccak(bytes('MyLog(bytes3)', 'utf-8'))

    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'name': 'MyLog', 'inputs': [{'type': 'bytes3', 'name': 'arg1', 'indexed': True}], 'anonymous': False, 'type': 'event'}
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].event == 'MyLog'
    assert logs[0].args.arg1 == b'bar'


def test_event_logging_with_multiple_topics(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[3]), arg2: indexed(bytes[4]), arg3: indexed(address)})

@public
def foo():
    log.MyLog('bar', 'home', self)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(bytes3,bytes4,address)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        'name': 'MyLog',
        'inputs': [
            {'type': 'bytes3', 'name': 'arg1', 'indexed': True},
            {'type': 'bytes4', 'name': 'arg2', 'indexed': True},
            {'type': 'address', 'name': 'arg3', 'indexed': True}],
        'anonymous': False,
        'type': 'event'
    }
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].event == 'MyLog'
    assert logs[0].args.arg1 == b'bar'
    assert logs[0].args.arg2 == b'home'
    assert logs[0].args.arg3 == c._classic_contract.address


def test_event_logging_with_multiple_topics_var_and_store(tester, get_contract_with_gas_estimation, get_logs):
    code = """
MyLog: event({arg1: indexed(bytes[3]), arg2: indexed(bytes[4]), arg3: indexed(address), arg4: bytes[10]})
b: bytes[10]

@public
def foo(arg1: bytes[3]):
    a: bytes[4] = 'home'
    self.b = 'hellothere'
    log.MyLog(arg1, a,  self, self.b)
    """

    c = get_contract_with_gas_estimation(code)
    tx_hash = c.foo(b'hel', transact={})

    # Event is decoded correctly
    log = get_logs(tx_hash, c, 'MyLog')[0]

    assert log.args.arg1 == b'hel'
    assert log.args.arg2 == b'home'
    assert log.args.arg3 == c.address
    assert log.args.arg4 == b'hellothere'


def test_logging_the_same_event_multiple_times_with_topics(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128), arg2: indexed(address)})

@public
def foo():
    log.MyLog(1, self)
    log.MyLog(1, self)

@public
def bar():
    log.MyLog(1, self)
    log.MyLog(1, self)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash1 = c.foo(transact={})
    tx_hash2 = c.bar(transact={})
    receipt1 = tester.get_transaction_receipt(tx_hash1.hex())
    receipt2 = tester.get_transaction_receipt(tx_hash2.hex())

    event_id = keccak(bytes('MyLog(int128,address)', 'utf-8'))
    # Event id is always the first topic
    assert receipt1['logs'][0]['topics'][0] == event_id.hex()
    assert receipt2['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        'name': 'MyLog',
        'inputs': [
            {'type': 'int128', 'name': 'arg1', 'indexed': True},
            {'type': 'address', 'name': 'arg2', 'indexed': True}],
        'anonymous': False,
        'type': 'event'
    }

    # Event is decoded correctly
    logs = get_logs(tx_hash1, c, 'MyLog')
    assert logs[0].args.arg1 == 1
    assert logs[0].args.arg2 == c.address
    assert logs[1].args.arg1 == 1
    assert logs[1].args.arg2 == c.address


def test_event_logging_cannot_have_more_than_three_topics(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[3]), arg2: indexed(bytes[4]), arg3: indexed(address), arg4: indexed(int128)})
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_event_logging_with_data(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: int128})

@public
def foo():
    log.MyLog(123)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(int128)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'name': 'MyLog', 'inputs': [{'type': 'int128', 'name': 'arg1', 'indexed': False}], 'anonymous': False, 'type': 'event'}

    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].args.arg1 == 123


def test_event_logging_with_units(get_contract_with_gas_estimation):
    code = """
MyLog: event({arg1: indexed(int128(wei)), arg2: int128(wei)})

@public
def foo():
    log.MyLog(1, 2)
"""
    get_contract_with_gas_estimation(code)


def test_event_logging_with_fixed_array_data(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: int128[2], arg2: timestamp[3], arg3: int128[2][2]})

@public
def foo():
    log.MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    log.MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(int128[2],uint256[3],int128[2][2])', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly

    assert c._classic_contract.abi[0] == {
        'name': 'MyLog',
        'inputs': [
            {'type': 'int128[2]', 'name': 'arg1', 'indexed': False},
            {'type': 'uint256[3]', 'name': 'arg2', 'indexed': False},
            {'type': 'int128[2][2]', 'name': 'arg3', 'indexed': False}],
        'anonymous': False,
        'type': 'event'
    }

    # Event is decoded correctly
    timestamp = w3.eth.getBlock(w3.eth.blockNumber).timestamp
    logs = get_logs(tx_hash, c, 'MyLog')

    assert logs[0].args.arg1 == [1, 2]
    assert logs[0].args.arg2 == [timestamp, timestamp + 1, timestamp + 2]
    assert logs[0].args.arg3 == [[1, 2], [1, 2]]


def test_logging_with_input_bytes_1(w3, tester, keccak, get_logs, bytes_helper, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[4]), arg2: indexed(bytes[29]), arg3: bytes[31]})

@public
def foo(arg1: bytes[29], arg2: bytes[31]):
    log.MyLog('bar', arg1, arg2)
"""

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(b'bar', b'foo', transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(bytes4,bytes29,bytes)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        'name': 'MyLog',
        'inputs': [
            {'type': 'bytes4', 'name': 'arg1', 'indexed': True},
            {'type': 'bytes29', 'name': 'arg2', 'indexed': True},
            {'type': 'bytes', 'name': 'arg3', 'indexed': False}],
        'anonymous': False, 'type': 'event'
    }
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')

    assert logs[0].args.arg1 == b'bar\x00'
    assert logs[0].args.arg2 == bytes_helper('bar', 29)
    assert logs[0].args.arg3 == b'foo'


def test_event_logging_with_bytes_input_2(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: bytes[20]})

@public
def foo(_arg1: bytes[20]):
    log.MyLog(_arg1)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(b'hello', transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(bytes)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'anonymous': False, 'inputs': [{'indexed': False, 'name': 'arg1', 'type': 'bytes'}], 'name': 'MyLog', 'type': 'event'}
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].args.arg1 == b'hello'


def test_event_logging_with_bytes_input_3(w3, tester, keccak, get_logs, get_contract):
    loggy_code = """
MyLog: event({arg1: bytes[5]})

@public
def foo(_arg1: bytes[5]):
    log.MyLog(_arg1)
    """

    c = get_contract(loggy_code)
    tx_hash = c.foo(b'hello', transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(bytes)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'anonymous': False, 'inputs': [{'indexed': False, 'name': 'arg1', 'type': 'bytes'}], 'name': 'MyLog', 'type': 'event'}
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].args.arg1 == b'hello'


def test_event_logging_with_data_with_different_types(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: int128, arg2: bytes[4], arg3: bytes[3], arg4: address, arg5: address, arg6: timestamp})

@public
def foo():
    log.MyLog(123, 'home', 'bar', 0xc305c901078781C232A2a521C2aF7980f8385ee9, self, block.timestamp)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(int128,bytes,bytes,address,address,uint256)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        'name': 'MyLog',
        'inputs': [{'type': 'int128', 'name': 'arg1', 'indexed': False},
                   {'type': 'bytes', 'name': 'arg2', 'indexed': False},
                   {'type': 'bytes', 'name': 'arg3', 'indexed': False},
                   {'type': 'address', 'name': 'arg4', 'indexed': False},
                   {'type': 'address', 'name': 'arg5', 'indexed': False},
                   {'type': 'uint256', 'name': 'arg6', 'indexed': False}],
        'anonymous': False,
        'type': 'event'
    }

    # Event is decoded correctly
    timestamp = w3.eth.getBlock(w3.eth.blockNumber).timestamp
    logs = get_logs(tx_hash, c, 'MyLog')
    args = logs[0].args
    assert args.arg1 == 123
    assert args.arg2 == b'home'
    assert args.arg3 == b'bar'
    assert args.arg4 == '0xc305c901078781C232A2a521C2aF7980f8385ee9'
    assert args.arg5 == c.address
    assert args.arg6 == timestamp


def test_event_logging_with_topics_and_data_1(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128), arg2: bytes[3]})

@public
def foo():
    log.MyLog(1, 'bar')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes('MyLog(int128,bytes)', 'utf-8'))
    # Event id is always the first topic
    assert receipt['logs'][0]['topics'][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        'anonymous': False,
        'inputs': [
            {'indexed': True, 'name': 'arg1', 'type': 'int128'},
            {'indexed': False, 'name': 'arg2', 'type': 'bytes'}], 'name': 'MyLog', 'type': 'event'}
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    args = logs[0].args
    assert args.arg1 == 1
    assert args.arg2 == b'bar'


def test_event_logging_with_multiple_logs_topics_and_data(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128), arg2: bytes[3]})
YourLog: event({arg1: indexed(address), arg2: bytes[5]})

@public
def foo():
    log.MyLog(1, 'bar')
    log.YourLog(self, 'house')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    logs1 = receipt['logs'][0]
    logs2 = receipt['logs'][1]
    event_id1 = keccak(bytes('MyLog(int128,bytes)', 'utf-8'))
    event_id2 = keccak(bytes('YourLog(address,bytes)', 'utf-8'))

    # Event id is always the first topic
    assert logs1['topics'][0] == event_id1.hex()
    assert logs2['topics'][0] == event_id2.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {'name': 'MyLog', 'inputs': [{'type': 'int128', 'name': 'arg1', 'indexed': True}, {'type': 'bytes', 'name': 'arg2', 'indexed': False}], 'anonymous': False, 'type': 'event'}
    assert c._classic_contract.abi[1] == {'name': 'YourLog', 'inputs': [{'type': 'address', 'name': 'arg1', 'indexed': True}, {'type': 'bytes', 'name': 'arg2', 'indexed': False}], 'anonymous': False, 'type': 'event'}

    # Event is decoded correctly
    logs = get_logs(tx_hash, c, 'MyLog')
    args = logs[0].args
    assert args.arg1 == 1
    assert args.arg2 == b'bar'
    logs = get_logs(tx_hash, c, 'YourLog')
    args = logs[0].args
    assert args.arg1 == c.address
    assert args.arg2 == b'house'


def test_fails_when_input_is_the_wrong_type(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128)})

@public
def foo_():
    log.MyLog('yo')
"""

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_topic_is_the_wrong_size(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[3])})

@public
def foo():
    log.MyLog('bars')
"""

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_input_topic_is_the_wrong_size(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[3])})

@public
def foo(arg1: bytes[4]):
    log.MyLog(arg1)
"""

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_data_is_the_wrong_size(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: bytes[3]})

@public
def foo():
    log.MyLog('bars')
"""

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_input_data_is_the_wrong_size(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: bytes[3]})

@public
def foo(arg1: bytes[4]):
    log.MyLog(arg1)
"""

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_topic_is_over_32_bytes(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(bytes[100])})

@public
def foo():
    pass
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_with_over_three_topics(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128), arg2: indexed(int128), arg3: indexed(int128), arg4: indexed(int128)})
@public
def __init__():
    log.MyLog(1, 2, 3, 4)
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_with_duplicate_log_names(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({})
MyLog: event({})

@public
def foo():
    log.MyLog()
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_with_when_log_is_undeclared(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """

@public
def foo():
    log.MyLog()
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_with_topic_type_mismatch(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: indexed(int128)})

@public
def foo():
    log.MyLog(self)
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_logging_fails_with_data_type_mismatch(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: bytes[3]})

@public
def foo():
    log.MyLog(self)
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_logging_fails_after_a_global_declaration(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
age: int128
MyLog: event({arg1: bytes[3]})
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_after_a_function_declaration(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
@public
def foo():
    pass

MyLog: event({arg1: bytes[3]})
    """
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_when_number_of_arguments_is_greater_than_declaration(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: int128})

@public
def foo():
    log.MyLog(1, 2)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_logging_fails_when_number_of_arguments_is_less_than_declaration(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: event({arg1: int128, arg2: int128})

@public
def foo():
    log.MyLog(1)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), EventDeclarationException)


def test_loggy_code(w3, tester, get_contract_with_gas_estimation):
    loggy_code = """
s: bytes[100]

@public
def foo():
    raw_log([], "moo")

@public
def goo():
    raw_log([0x1234567812345678123456781234567812345678123456781234567812345678], "moo2")

@public
def hoo():
    self.s = "moo3"
    raw_log([], self.s)

@public
def ioo(inp: bytes[100]):
    raw_log([], inp)
    """

    c = get_contract_with_gas_estimation(loggy_code)

    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt['logs']

    assert w3.toText(logs[0]['data']) == 'moo'
    tx_hash = c.goo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt['logs']
    assert w3.toText(logs[0]['data']) == 'moo2'
    assert logs[0]['topics'][0] == '0x1234567812345678123456781234567812345678123456781234567812345678'

    tx_hash = c.hoo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt['logs']
    assert w3.toText(logs[0]['data']) == 'moo3'

    tx_hash = c.ioo(b"moo4", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt['logs']
    assert w3.toText(logs[0]['data']) == 'moo4'

    print("Passed raw log tests")


def test_variable_list_packing(get_logs, get_contract_with_gas_estimation):

    code = """
Bar: event({_value: int128[4]})

@public
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log.Bar(a)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [1, 2, 3, 4]


def test_literal_list_packing(get_logs, get_contract_with_gas_estimation):

    code = """
Bar: event({_value: int128[4]})

@public
def foo():
    log.Bar([1, 2, 3, 4])
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [1, 2, 3, 4]


def test_storage_list_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):

    code = """
Bar: event({_value: int128[4]})
x: int128[4]

@public
def foo():
    log.Bar(self.x)

@public
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [0, 0, 0, 0]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [1, 2, 3, 4]


def test_passed_list_packing(get_logs, get_contract_with_gas_estimation):

    code = """
Bar: event({_value: int128[4]})

@public
def foo(barbaric: int128[4]):
    log.Bar(barbaric)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo([4, 5, 6, 7], transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [4, 5, 6, 7]


def test_variable_decimal_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
Bar: event({_value: decimal[4]})

@public
def foo():
    log.Bar([1.11, 2.22, 3.33, 4.44])
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [Decimal('1.11'), Decimal('2.22'), Decimal('3.33'), Decimal('4.44')]


def test_storage_byte_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):

    code = """
MyLog: event({arg1: bytes[29]})
x:bytes[5]

@public
def foo(a: int128):
    log.MyLog(self.x)

@public
def setbytez():
    self.x = 'hello'
    """

    c = get_contract_with_gas_estimation(code)
    tx_hash = c.foo(0, transact={})
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].args.arg1 == b''
    c.setbytez(transact={})
    tx_hash = c.foo(0, transact={})
    logs = get_logs(tx_hash, c, 'MyLog')
    assert logs[0].args.arg1 == b'hello'


def test_storage_decimal_list_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):

    code = """
Bar: event({_value: decimal[4]})
x: decimal[4]

@public
def foo():
    log.Bar(self.x)

@public
def set_list():
    self.x = [1.33, 2.33, 3.33, 4.33]
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [Decimal('0'), Decimal('0'), Decimal('0'), Decimal('0')]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, 'Bar')
    assert logs[0].args._value == [Decimal('1.33'), Decimal('2.33'), Decimal('3.33'), Decimal('4.33')]


def test_logging_fails_when_declartation_is_too_big(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
Bar: event({_value: indexed(bytes[33])})
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), EventDeclarationException)


def test_logging_fails_when_input_is_too_big(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
Bar: event({_value: indexed(bytes[32])})

@public
def foo(inp: bytes[33]):
    log.Bar(inp)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)


def test_2nd_var_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
Bar: event({arg1: int128, arg2: int128[4]})

@public
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log.Bar(10, a)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, 'Bar')[0].args.arg2 == [1, 2, 3, 4]


def test_2nd_var_storage_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
Bar: event({arg1: int128, arg2: int128[4]})
x: int128[4]

@public
def foo():
    log.Bar(10, self.x)

@public
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, 'Bar')[0].args.arg2 == [0, 0, 0, 0]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, 'Bar')[0].args.arg2 == [1, 2, 3, 4]


def test_mixed_var_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
Bar: event({arg1: int128, arg2: int128[4], arg3 :bytes[4], arg4: int128[3], arg5: int128[2]})
x: int128[4]
y: int128[2]

@public
def __init__():
    self.y = [1024, 2048]

@public
def foo():
    v: int128[3] = [7, 8, 9]
    log.Bar(10, self.x, "test", v, self.y)

@public
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    log = get_logs(tx_hash, c, 'Bar')[0]
    assert log.args["arg2"] == [0, 0, 0, 0]
    assert log.args["arg3"] == b"test"
    assert log.args["arg4"] == [7, 8, 9]
    assert log.args["arg5"] == [1024, 2048]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    log = get_logs(tx_hash, c, 'Bar')[0]
    assert log.args["arg2"] == [1, 2, 3, 4]
    assert log.args["arg3"] == b"test"
    assert log.args["arg4"] == [7, 8, 9]
    assert log.args["arg5"] == [1024, 2048]
