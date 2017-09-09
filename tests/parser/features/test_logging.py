import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract, assert_tx_failed
from viper.exceptions import VariableDeclarationException, TypeMismatchException, StructureException


def test_empy_event_logging():
    loggy_code = """
MyLog: __log__({})

def foo():
    log.MyLog()
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog()', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': [], 'name': 'MyLog', 'names': [], 'indexed': [], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'_event_type': b'MyLog'}


def test_event_logging_with_topics():
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3)})

def foo():
    log.MyLog('bar')
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(bytes3)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes3'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [True], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'bar', '_event_type': b'MyLog'}


def test_event_logging_with_multiple_topics():
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3), arg2: indexed(bytes <= 4), arg3: indexed(address)})

def foo():
    log.MyLog('bar', 'home', self)
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(bytes3,bytes4,address)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes3','bytes4','address'], 'name': 'MyLog', 'names': ['arg1','arg2','arg3'], 'indexed': [True, True, True], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'bar', 'arg2': b'home', 'arg3': '0x'+c.address.hex(), '_event_type': b'MyLog'}


def test_event_logging_cannot_have_more_than_three_topics():
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3), arg2: indexed(bytes <= 4), arg3: indexed(address), arg4: indexed(num)})

def foo():
    log.MyLog('bar', 'home', self)
    """

    with pytest.raises(VariableDeclarationException):
        get_contract(loggy_code)


def test_event_logging_with_data():
    loggy_code = """
MyLog: __log__({arg1: num})

def foo():
    log.MyLog(123)
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(int128)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 123, '_event_type': b'MyLog'}


def test_event_loggging_with_fixed_array_data():
    loggy_code = """
MyLog: __log__({arg1: num[2], arg2: timestamp[3], arg3: num[2][2]})

def foo():
    log.MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
#     """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(int128[2],int128[3],int128[2][2])', 'utf-8')))
    # # Event id is always the first topic
    assert logs.topics[0] == event_id
    # # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128[2]', 'int128[3]', 'int128[2][2]'], 'name': 'MyLog', 'names': ['arg1', 'arg2', 'arg3'], 'indexed': [False, False, False], 'anonymous': False}
    # # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': [1, 2], 'arg2': [1467446892, 1467446893, 1467446894], 'arg3': [[1, 2], [1, 2]], '_event_type': b'MyLog'}


def test_event_logging_with_data_with_different_types():
    loggy_code = """
MyLog: __log__({arg1: num, arg2: bytes <= 4, arg3: bytes <= 3, arg4: address, arg5: address, arg6: timestamp})

def foo():
    log.MyLog(123, 'home', 'bar', 0xc305c901078781C232A2a521C2aF7980f8385ee9, self, block.timestamp)
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(int128,bytes4,bytes3,address,address,int128)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128', 'bytes4', 'bytes3', 'address', 'address', 'int128'], 'name': 'MyLog', 'names': ['arg1', 'arg2', 'arg3', 'arg4', 'arg5', 'arg6'], 'indexed': [False, False, False, False, False, False], 'anonymous': False}

    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 123, 'arg2': b'home', 'arg3': b'bar', 'arg4': '0xc305c901078781c232a2a521c2af7980f8385ee9', 'arg5': '0x' + c.address.hex(), 'arg6': 1467446892, '_event_type': b'MyLog'}


def test_event_logging_with_topics_and_data():
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: bytes <= 3})

def foo():
    log.MyLog(1, 'bar')
    """

    c = get_contract(loggy_code)
    c.foo()
    logs = s.head_state.receipts[-1].logs[-1]
    event_id = u.bytes_to_int(u.sha3(bytes('MyLog(int128,bytes3)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128','bytes3'], 'name': 'MyLog', 'names': ['arg1','arg2'], 'indexed': [True, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 1, 'arg2': b'bar', '_event_type': b'MyLog'}


def test_event_logging_with_multiple_logs_topics_and_data():
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: bytes <= 3})
YourLog: __log__({arg1: indexed(address), arg2: bytes <= 5})

def foo():
    log.MyLog(1, 'bar')
    log.YourLog(self, 'house')
    """

    c = get_contract(loggy_code)
    c.foo()
    logs1 = s.head_state.receipts[-1].logs[-2]
    logs2 = s.head_state.receipts[-1].logs[-1]
    event_id1 = u.bytes_to_int(u.sha3(bytes('MyLog(int128,bytes3)', 'utf-8')))
    event_id2 = u.bytes_to_int(u.sha3(bytes('YourLog(address,bytes5)', 'utf-8')))
    # Event id is always the first topic
    assert logs1.topics[0] == event_id1
    assert logs2.topics[0] == event_id2
    # Event ids are calculated correctly
    assert c.translator.event_data[event_id1]
    assert c.translator.event_data[event_id2]
    # Event abi is created correctly
    assert c.translator.event_data[event_id1] == {'types': ['int128','bytes3'], 'name': 'MyLog', 'names': ['arg1','arg2'], 'indexed': [True, False], 'anonymous': False}
    assert c.translator.event_data[event_id2] == {'types': ['address','bytes5'], 'name': 'YourLog', 'names': ['arg1','arg2'], 'indexed': [True, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs1.topics, logs1.data) == {'arg1': 1, 'arg2': b'bar', '_event_type': b'MyLog'}
    assert c.translator.decode_event(logs2.topics, logs2.data) == {'arg1': '0x' + c.address.hex(), 'arg2': b'house', '_event_type': b'YourLog'}



def test_logging_fails_with_over_three_topics(assert_tx_failed):
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: indexed(num), arg3: indexed(num), arg4: indexed(num)})
def __init__():
    log.MyLog(1, 2, 3, 4)
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), VariableDeclarationException)


def test_logging_fails_with_duplicate_log_names(assert_tx_failed):
    loggy_code = """
MyLog: __log__({})
MyLog: __log__({})

def foo():
    log.MyLog()
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), VariableDeclarationException)


def test_logging_fails_with_when_log_is_undeclared(assert_tx_failed):
    loggy_code = """
def foo():
    log.MyLog()
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), VariableDeclarationException)


def test_logging_fails_with_topic_type_mismatch(assert_tx_failed):
    loggy_code = """
MyLog: __log__({arg1: indexed(num)})

def foo():
    log.MyLog(self)
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), TypeMismatchException)


def test_logging_fails_with_data_type_mismatch(assert_tx_failed):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 3})

def foo():
    log.MyLog(self)
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), AttributeError)


def test_logging_fails_after_a_global_declaration(assert_tx_failed):
    loggy_code = """
age: num
MyLog: __log__({arg1: bytes <= 3})
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), StructureException)


def test_logging_fails_after_a_function_declaration(assert_tx_failed):
    loggy_code = """
def foo():
    pass

MyLog: __log__({arg1: bytes <= 3})
    """
    t.s = s
    assert_tx_failed(t, lambda: get_contract(loggy_code), StructureException)


def test_loggy_code():
    loggy_code = """
s: bytes <= 100

def foo():
    raw_log([], "moo")

def goo():
    raw_log([0x1234567812345678123456781234567812345678123456781234567812345678], "moo2")

def hoo():
    self.s = "moo3"
    raw_log([], self.s)

def ioo(inp: bytes <= 100):
    raw_log([], inp)
    """

    c = get_contract(loggy_code)
    c.foo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo'
    c.goo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo2'
    assert s.head_state.receipts[-1].logs[0].topics == [0x1234567812345678123456781234567812345678123456781234567812345678]
    c.hoo()
    assert s.head_state.receipts[-1].logs[0].data == b'moo3'
    c.ioo(b"moo4")
    assert s.head_state.receipts[-1].logs[0].data == b'moo4'
    print("Passed raw log tests")
