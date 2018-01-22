from viper.exceptions import VariableDeclarationException, TypeMismatchException, StructureException


def test_empy_event_logging(get_contract_with_gas_estimation, utils, chain):
    loggy_code = """
MyLog: __log__({})

@public
def foo():
    log.MyLog()
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog()', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': [], 'name': 'MyLog', 'names': [], 'indexed': [], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'_event_type': b'MyLog'}


def test_event_logging_with_topics(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3)})

@public
def foo():
    log.MyLog('bar')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(bytes3)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes3'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [True], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'bar', '_event_type': b'MyLog'}


def test_event_logging_with_multiple_topics(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3), arg2: indexed(bytes <= 4), arg3: indexed(address)})

@public
def foo():
    log.MyLog('bar', 'home', self)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(bytes3,bytes4,address)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == (
        {'types': ['bytes3', 'bytes4', 'address'],
        'name': 'MyLog',
        'names': ['arg1', 'arg2', 'arg3'],
        'indexed': [True, True, True],
        'anonymous': False}
    )
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'bar', 'arg2': b'home', 'arg3': '0x' + c.address.hex(), '_event_type': b'MyLog'}


def test_logging_the_same_event_multiple_times_with_topics(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: indexed(address)})

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
    c.foo()
    c.bar()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128,address)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128', 'address'], 'name': 'MyLog', 'names': ['arg1', 'arg2'], 'indexed': [True, True], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'_event_type': b'MyLog', 'arg1': 1, 'arg2': '0x' + c.address.hex()}


def test_event_logging_cannot_have_more_than_three_topics(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3), arg2: indexed(bytes <= 4), arg3: indexed(address), arg4: indexed(num)})
    """

    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_event_logging_with_data(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: num})

@public
def foo():
    log.MyLog(123)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 123, '_event_type': b'MyLog'}


def test_event_logging_with_units(get_contract_with_gas_estimation, chain, utils):
    code = """
MyLog: __log__({arg1: indexed(num(wei)), arg2: num(wei)})

@public
def foo():
    log.MyLog(1, 2)
"""
    get_contract_with_gas_estimation(code)


def test_event_logging_with_fixed_array_data(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: num[2], arg2: timestamp[3], arg3: num[2][2]})

@public
def foo():
    log.MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    log.MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128[2],int128[3],int128[2][2])', 'utf-8')))
    # # Event id is always the first topic
    assert logs.topics[0] == event_id
    # # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128[2]', 'int128[3]', 'int128[2][2]'], 'name': 'MyLog', 'names': ['arg1', 'arg2', 'arg3'], 'indexed': [False, False, False], 'anonymous': False}
    # # Event is decoded correctly
    timestamp = chain.head_state.timestamp
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': [1, 2], 'arg2': [timestamp, timestamp + 1, timestamp + 2], 'arg3': [[1, 2], [1, 2]], '_event_type': b'MyLog'}


def test_logging_with_input_bytes_1(bytes_helper, get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 4), arg2: indexed(bytes <= 29), arg3: bytes<=31})

@public
def foo(arg1: bytes <= 29, arg2: bytes <= 31):
    log.MyLog('bar', arg1, arg2)
"""

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo('bar', 'foo')
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(bytes4,bytes29,bytes)', 'utf-8')))
    # # Event id is always the first topic
    assert logs.topics[0] == event_id
    # # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes4', 'bytes29', 'bytes'], 'name': 'MyLog', 'names': ['arg1', 'arg2', 'arg3'], 'indexed': [True, True, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {
        'arg1': b'bar\x00',
        'arg2': bytes_helper('bar', 29),
        'arg3': b'foo',
        '_event_type': b'MyLog'
    }


def test_event_logging_with_bytes_input_2(t, bytes_helper, get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 20})

@public
def foo(_arg1: bytes <= 20):
    log.MyLog(_arg1)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo('hello')
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(bytes)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'hello', '_event_type': b'MyLog'}


def test_event_logging_with_bytes_input_3(get_contract, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 5})

@public
def foo(_arg1: bytes <= 5):
    log.MyLog(_arg1)
    """

    c = get_contract(loggy_code)
    c.foo('hello')
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(bytes)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['bytes'], 'name': 'MyLog', 'names': ['arg1'], 'indexed': [False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': b'hello', '_event_type': b'MyLog'}


def test_event_logging_with_data_with_different_types(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: num, arg2: bytes <= 4, arg3: bytes <= 3, arg4: address, arg5: address, arg6: timestamp})

@public
def foo():
    log.MyLog(123, 'home', 'bar', 0xc305c901078781C232A2a521C2aF7980f8385ee9, self, block.timestamp)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128,bytes,bytes,address,address,int128)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128', 'bytes', 'bytes', 'address', 'address', 'int128'], 'name': 'MyLog', 'names': ['arg1', 'arg2', 'arg3', 'arg4', 'arg5', 'arg6'], 'indexed': [False, False, False, False, False, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 123, 'arg2': b'home', 'arg3': b'bar', 'arg4': '0xc305c901078781c232a2a521c2af7980f8385ee9', 'arg5': '0x' + c.address.hex(), 'arg6': chain.head_state.timestamp, '_event_type': b'MyLog'}


def test_event_logging_with_topics_and_data_1(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: bytes <= 3})

@public
def foo():
    log.MyLog(1, 'bar')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs = chain.head_state.receipts[-1].logs[-1]
    event_id = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128,bytes)', 'utf-8')))
    # Event id is always the first topic
    assert logs.topics[0] == event_id
    # Event id is calculated correctly
    assert c.translator.event_data[event_id]
    # Event abi is created correctly
    assert c.translator.event_data[event_id] == {'types': ['int128', 'bytes'], 'name': 'MyLog', 'names': ['arg1', 'arg2'], 'indexed': [True, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs.topics, logs.data) == {'arg1': 1, 'arg2': b'bar', '_event_type': b'MyLog'}


def test_event_logging_with_multiple_logs_topics_and_data(get_contract_with_gas_estimation, chain, utils):
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: bytes <= 3})
YourLog: __log__({arg1: indexed(address), arg2: bytes <= 5})

@public
def foo():
    log.MyLog(1, 'bar')
    log.YourLog(self, 'house')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    logs1 = chain.head_state.receipts[-1].logs[-2]
    logs2 = chain.head_state.receipts[-1].logs[-1]
    event_id1 = utils.bytes_to_int(utils.sha3(bytes('MyLog(int128,bytes)', 'utf-8')))
    event_id2 = utils.bytes_to_int(utils.sha3(bytes('YourLog(address,bytes)', 'utf-8')))
    # Event id is always the first topic
    assert logs1.topics[0] == event_id1
    assert logs2.topics[0] == event_id2
    # Event ids are calculated correctly
    assert c.translator.event_data[event_id1]
    assert c.translator.event_data[event_id2]
    # Event abi is created correctly
    assert c.translator.event_data[event_id1] == {'types': ['int128', 'bytes'], 'name': 'MyLog', 'names': ['arg1', 'arg2'], 'indexed': [True, False], 'anonymous': False}
    assert c.translator.event_data[event_id2] == {'types': ['address', 'bytes'], 'name': 'YourLog', 'names': ['arg1', 'arg2'], 'indexed': [True, False], 'anonymous': False}
    # Event is decoded correctly
    assert c.translator.decode_event(logs1.topics, logs1.data) == {'arg1': 1, 'arg2': b'bar', '_event_type': b'MyLog'}
    assert c.translator.decode_event(logs2.topics, logs2.data) == {'arg1': '0x' + c.address.hex(), 'arg2': b'house', '_event_type': b'YourLog'}


def test_fails_when_input_is_the_wrong_type(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(num)})

@public
def foo_():
    log.MyLog('yo')
"""
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_topic_is_the_wrong_size(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3)})

@public
def foo():
    log.MyLog('bars')
"""
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_input_topic_is_the_wrong_size(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 3)})

@public
def foo(arg1: bytes <= 4):
    log.MyLog(arg1)
"""
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_data_is_the_wrong_size(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 3})

@public
def foo():
    log.MyLog('bars')
"""
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_input_data_is_the_wrong_size(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 3})

@public
def foo(arg1: bytes <= 4):
    log.MyLog(arg1)
"""
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_fails_when_topic_is_over_32_bytes(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(bytes <= 100)})

@public
def foo():
    pass
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_logging_fails_with_over_three_topics(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(num), arg2: indexed(num), arg3: indexed(num), arg4: indexed(num)})
@public
def __init__():
    log.MyLog(1, 2, 3, 4)
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_logging_fails_with_duplicate_log_names(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({})
MyLog: __log__({})

@public
def foo():
    log.MyLog()
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_logging_fails_with_when_log_is_undeclared(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """

@public
def foo():
    log.MyLog()
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_logging_fails_with_topic_type_mismatch(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: indexed(num)})

@public
def foo():
    log.MyLog(self)
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_logging_fails_with_data_type_mismatch(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
MyLog: __log__({arg1: bytes <= 3})

@public
def foo():
    log.MyLog(self)
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), TypeMismatchException)


def test_logging_fails_after_a_global_declaration(t, assert_tx_failed, get_contract_with_gas_estimation, chain):
    loggy_code = """
age: num
MyLog: __log__({arg1: bytes <= 3})
    """
    t.s = chain
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), StructureException)


def test_logging_fails_after_a_function_declaration(t, assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
@public
def foo():
    pass

MyLog: __log__({arg1: bytes <= 3})
    """
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), StructureException)


def test_logging_fails_when_number_of_arguments_is_greater_than_declaration(t, assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: __log__({arg1: num})

@public
def foo():
    log.MyLog(1, 2)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_logging_fails_when_number_of_arguments_is_less_than_declaration(assert_tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
MyLog: __log__({arg1: num, arg2: num})

@public
def foo():
    log.MyLog(1)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(loggy_code), VariableDeclarationException)


def test_loggy_code(get_contract_with_gas_estimation, chain):
    loggy_code = """
s: bytes <= 100

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
def ioo(inp: bytes <= 100):
    raw_log([], inp)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    c.foo()
    assert chain.head_state.receipts[-1].logs[0].data == b'moo'
    c.goo()
    assert chain.head_state.receipts[-1].logs[0].data == b'moo2'
    assert chain.head_state.receipts[-1].logs[0].topics == [0x1234567812345678123456781234567812345678123456781234567812345678]
    c.hoo()
    assert chain.head_state.receipts[-1].logs[0].data == b'moo3'
    c.ioo(b"moo4")
    assert chain.head_state.receipts[-1].logs[0].data == b'moo4'
    print("Passed raw log tests")


def test_variable_list_packing(t, get_last_log, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
Bar: __log__({_value: num[4]})

@public
def foo():
    a: num[4] = [1, 2, 3, 4]
    log.Bar(a)
    """
    c = get_contract_with_gas_estimation(code)

    c.foo()
    assert get_last_log(t, c)["_value"] == [1, 2, 3, 4]


def test_literal_list_packing(t, get_last_log, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
Bar: __log__({_value: num[4]})

@public
def foo():
    log.Bar([1, 2, 3, 4])
    """
    c = get_contract_with_gas_estimation(code)

    c.foo()
    assert get_last_log(t, c)["_value"] == [1, 2, 3, 4]


def test_storage_list_packing(t, get_last_log, bytes_helper, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
Bar: __log__({_value: num[4]})
x: num[4]

@public
def foo():
    log.Bar(self.x)

@public
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract_with_gas_estimation(code)

    c.foo()
    assert get_last_log(t, c)["_value"] == [0, 0, 0, 0]
    c.set_list()
    c.foo()
    assert get_last_log(t, c)["_value"] == [1, 2, 3, 4]


def test_passed_list_packing(t, get_last_log, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
Bar: __log__({_value: num[4]})

@public
def foo(barbaric: num[4]):
    log.Bar(barbaric)
    """
    c = get_contract_with_gas_estimation(code)

    c.foo([4, 5, 6, 7])
    assert get_last_log(t, c)["_value"] == [4, 5, 6, 7]


def test_variable_decimal_list_packing(t, get_last_log, get_contract_with_gas_estimation, chain):
    t.s = chain

    code = """
Bar: __log__({_value: decimal[4]})

@public
def foo():
    log.Bar([1.11, 2.22, 3.33, 4.44])
    """
    c = get_contract_with_gas_estimation(code)

    c.foo()
    assert get_last_log(t, c)["_value"] == [1.11, 2.22, 3.33, 4.44]


def test_storage_byte_packing(t, get_last_log, bytes_helper, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
MyLog: __log__({arg1: bytes <= 29})
x:bytes<=5

@public
def foo(a:num):
    log.MyLog(self.x)

@public
def setbytez():
    self.x = 'hello'
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()
    assert get_last_log(t, c)['arg1'] == b''
    c.setbytez()
    c.foo()
    assert get_last_log(t, c)['arg1'] == b'hello'


def test_storage_decimal_list_packing(t, get_last_log, bytes_helper, get_contract_with_gas_estimation, chain):
    t.s = chain
    code = """
Bar: __log__({_value: decimal[4]})
x: decimal[4]

@public
def foo():
    log.Bar(self.x)

@public
def set_list():
    self.x = [1.33, 2.33, 3.33, 4.33]
    """
    c = get_contract_with_gas_estimation(code)

    c.foo()
    assert get_last_log(t, c)["_value"] == [0, 0, 0, 0]
    c.set_list()
    c.foo()
    assert get_last_log(t, c)["_value"] == [1.33, 2.33, 3.33, 4.33]


def test_logging_fails_when_declartation_is_too_big(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
Bar: __log__({_value: indexed(bytes <= 33)})
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), VariableDeclarationException)


def test_logging_fails_when_input_is_too_big(assert_tx_failed, get_contract_with_gas_estimation):
    code = """
Bar: __log__({_value: indexed(bytes <= 32)})

@public
def foo(inp: bytes <= 33):
    log.Bar(inp)
"""
    assert_tx_failed(lambda: get_contract_with_gas_estimation(code), TypeMismatchException)
