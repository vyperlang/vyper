import pytest
from eth.codecs import abi
from eth_utils import to_text

from tests.utils import decimal_to_int
from vyper import compile_code
from vyper.exceptions import (
    ArgumentException,
    EventDeclarationException,
    InvalidType,
    NamespaceCollision,
    StructureException,
    TypeMismatch,
    UndeclaredDefinition,
)
from vyper.utils import keccak256


def test_empty_event_logging(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog: pass

@external
def foo():
    log MyLog()
    """

    c = get_contract(loggy_code)
    c.foo()
    (log,) = get_logs(c)

    event_id = keccak(bytes("MyLog()", "utf-8"))

    # Event id is always the first topic
    assert log.topics == [event_id]
    # Event abi is created correctly
    assert c.abi[0] == {"name": "MyLog", "inputs": [], "anonymous": False, "type": "event"}
    # Event is decoded correctly
    assert log.event == "MyLog"


def test_event_logging_with_topics(get_logs, keccak, get_contract):
    loggy_code = """

a: Bytes[3]

event MyLog:
    arg1: indexed(Bytes[3])

@external
def foo():
    self.a = b"bar"
    log MyLog(self.a)
    """

    c = get_contract(loggy_code)
    c.foo()
    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))

    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [{"type": "bytes", "name": "arg1", "indexed": True}],
        "anonymous": False,
        "type": "event",
    }


def test_event_logging_with_multiple_topics(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: indexed(bool)
    arg3: indexed(address)

@external
def foo():
    log MyLog(-2, True, self)
    """

    c = get_contract(loggy_code)
    c.foo()

    event_id = keccak(bytes("MyLog(int128,bool,address)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": True},
            {"type": "bool", "name": "arg2", "indexed": True},
            {"type": "address", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }
    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")
    assert log.event == "MyLog"
    assert log.args.arg1 == -2
    assert log.args.arg2 is True
    assert log.args.arg3 == c.address


def test_event_logging_with_multiple_topics_var_and_store(get_contract, get_logs):
    code = """
event MyLog:
    arg1: indexed(int128)
    arg2: indexed(bool)
    arg3: indexed(address)

b: address

@external
def foo(arg1: int128):
    a: bool = True
    self.b = self
    log MyLog(arg1, a, self.b)
    """

    c = get_contract(code)
    c.foo(31337)

    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == 31337
    assert log.args.arg2 is True
    assert log.args.arg3 == c.address


def test_logging_the_same_event_multiple_times_with_topics(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: indexed(address)

@external
def foo():
    log MyLog(1, self)
    log MyLog(1, self)

@external
def bar():
    log MyLog(1, self)
    log MyLog(1, self)
    """

    c = get_contract(loggy_code)
    c.foo()
    log1, log2 = get_logs(c)
    c.bar()
    log3, _ = get_logs(c)

    event_id = keccak(bytes("MyLog(int128,address)", "utf-8"))
    # Event id is always the first topic
    assert log1.topics[0] == event_id
    assert log3.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": True},
            {"type": "address", "name": "arg2", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    assert log1.args.arg1 == 1
    assert log1.args.arg2 == c.address
    assert log2.args.arg1 == 1
    assert log2.args.arg2 == c.address


def test_event_logging_cannot_have_more_than_three_topics(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])
    arg2: indexed(Bytes[4])
    arg3: indexed(address)
    arg4: indexed(int128)
    """

    with pytest.raises(EventDeclarationException):
        compile_code(loggy_code)


def test_event_logging_with_data(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: int128

@external
def foo():
    log MyLog(123)
    """

    c = get_contract(loggy_code)
    c.foo()

    event_id = keccak(bytes("MyLog(int128)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics == [event_id]
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [{"type": "int128", "name": "arg1", "indexed": False}],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == 123


def test_event_logging_with_fixed_array_data(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: int128[2]
    arg2: uint256[3]
    arg3: int128[2][2]


@external
def foo():
    log MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    log MyLog([1,2], [block.timestamp, block.timestamp+1, block.timestamp+2], [[1,2],[1,2]])
    """

    c = get_contract(loggy_code)
    c.foo()

    event_id = keccak(bytes("MyLog(int128[2],uint256[3],int128[2][2])", "utf-8"))
    # Event id is always the first topic
    log, _ = get_logs(c)
    assert log.topics == [event_id]
    # Event abi is created correctly

    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128[2]", "name": "arg1", "indexed": False},
            {"type": "uint256[3]", "name": "arg2", "indexed": False},
            {"type": "int128[2][2]", "name": "arg3", "indexed": False},
        ],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    timestamp = env.timestamp
    assert log.args.arg1 == [1, 2]
    assert log.args.arg2 == [timestamp, timestamp + 1, timestamp + 2]
    assert log.args.arg3 == [[1, 2], [1, 2]]


def test_logging_with_input_bytes_1(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[4]
    arg2: indexed(Bytes[29])
    arg3: Bytes[31]

@external
def foo(arg1: Bytes[29], arg2: Bytes[31]):
    log MyLog(b'bar', arg1, arg2)
"""

    c = get_contract(loggy_code)
    c.foo(b"bar", b"foo")

    event_id = keccak(bytes("MyLog(bytes,bytes,bytes)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": False},
            {"type": "bytes", "name": "arg2", "indexed": True},
            {"type": "bytes", "name": "arg3", "indexed": False},
        ],
        "anonymous": False,
        "type": "event",
    }
    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")

    assert log.args.arg1 == b"bar"
    assert log.args.arg2 == keccak(b"bar")
    assert log.args.arg3 == b"foo"


def test_event_logging_with_bytes_input_2(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[20]

@external
def foo(_arg1: Bytes[20]):
    log MyLog(_arg1)
    """

    c = get_contract(loggy_code)
    c.foo(b"hello")

    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "anonymous": False,
        "inputs": [{"indexed": False, "name": "arg1", "type": "bytes"}],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    assert log.args.arg1 == b"hello"


def test_event_logging_with_bytes_input_3(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[5]

@external
def foo(_arg1: Bytes[5]):
    log MyLog(_arg1)
    """

    c = get_contract(loggy_code)
    c.foo(b"hello")

    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics == [event_id]
    # Event abi is created correctly
    assert c.abi[0] == {
        "anonymous": False,
        "inputs": [{"indexed": False, "name": "arg1", "type": "bytes"}],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == b"hello"


def test_event_logging_with_data_with_different_types(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: int128
    arg2: Bytes[4]
    arg3: Bytes[3]
    arg4: address
    arg5: address
    arg6: uint256

@external
def foo():
    log MyLog(123, b'home', b'bar', 0xc305c901078781C232A2a521C2aF7980f8385ee9, self, block.timestamp)  # noqa: E501
    """

    c = get_contract(loggy_code)
    c.foo()

    event_id = keccak(bytes("MyLog(int128,bytes,bytes,address,address,uint256)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics == [event_id]
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": False},
            {"type": "bytes", "name": "arg2", "indexed": False},
            {"type": "bytes", "name": "arg3", "indexed": False},
            {"type": "address", "name": "arg4", "indexed": False},
            {"type": "address", "name": "arg5", "indexed": False},
            {"type": "uint256", "name": "arg6", "indexed": False},
        ],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    args = log.args
    assert args.arg1 == 123
    assert args.arg2 == b"home"
    assert args.arg3 == b"bar"
    assert args.arg4 == "0xc305c901078781C232A2a521C2aF7980f8385ee9"
    assert args.arg5 == c.address
    assert args.arg6 == env.timestamp


def test_event_logging_with_topics_and_data_1(env, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: Bytes[3]

@external
def foo():
    log MyLog(1, b'bar')
    """

    c = get_contract(loggy_code)
    c.foo()

    event_id = keccak(bytes("MyLog(int128,bytes)", "utf-8"))
    # Event id is always the first topic
    (log,) = get_logs(c)
    assert log.topics[0] == event_id
    # Event abi is created correctly
    assert c.abi[0] == {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "arg1", "type": "int128"},
            {"indexed": False, "name": "arg2", "type": "bytes"},
        ],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == 1
    assert log.args.arg2 == b"bar"


def test_event_logging_with_multiple_logs_topics_and_data(env, keccak, get_logs, get_contract):
    loggy_code = """
struct SmallStruct:
    t: String[5]
    w: decimal
struct MyStruct:
    x: uint256
    y: Bytes[3]
    z: SmallStruct

event MyLog:
    arg1: indexed(int128)
    arg2: Bytes[3]
event YourLog:
    arg1: indexed(address)
    arg2: MyStruct

@external
def foo():
    log MyLog(1, b'bar')
    log YourLog(self, MyStruct(x=1, y=b'abc', z=SmallStruct(t='house', w=13.5)))
    """

    c = get_contract(loggy_code)
    c.foo()

    log1, log2 = get_logs(c)
    event_id1 = keccak(bytes("MyLog(int128,bytes)", "utf-8"))
    event_id2 = keccak(bytes("YourLog(address,(uint256,bytes,(string,int168)))", "utf-8"))

    # Event id is always the first topic
    assert log1.topics[0] == event_id1
    assert log2.topics[0] == event_id2
    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": True},
            {"type": "bytes", "name": "arg2", "indexed": False},
        ],
        "anonymous": False,
        "type": "event",
    }
    assert c.abi[1] == {
        "name": "YourLog",
        "inputs": [
            {"name": "arg1", "type": "address", "indexed": True},
            {
                "name": "arg2",
                "type": "tuple",
                "components": [
                    {"name": "x", "type": "uint256"},
                    {"name": "y", "type": "bytes"},
                    {
                        "name": "z",
                        "type": "tuple",
                        "components": [
                            {"name": "t", "type": "string"},
                            {"name": "w", "type": "int168", "internalType": "decimal"},
                        ],
                    },
                ],
                "indexed": False,
            },
        ],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    (my_log,) = get_logs(c, "MyLog")
    assert my_log.args.arg1 == 1
    assert my_log.args.arg2 == b"bar"

    (your_log,) = get_logs(c, "YourLog")
    assert your_log.args.arg1 == c.address
    assert your_log.args.arg2 == (1, b"abc", ("house", decimal_to_int("13.5")))


def test_fails_when_input_is_the_wrong_type(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)

@external
def foo_():
    log MyLog(b'yo')
"""

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_fails_when_topic_is_the_wrong_size(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])


@external
def foo():
    log MyLog(b'bars')
"""

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_fails_when_input_topic_is_the_wrong_size(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])

@external
def foo(arg1: Bytes[4]):
    log MyLog(arg1)
"""

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_fails_when_data_is_the_wrong_size(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo():
    log MyLog(b'bars')
"""

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_fails_when_input_data_is_the_wrong_size(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo(arg1: Bytes[4]):
    log MyLog(arg1)
"""

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_topic_over_32_bytes(get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[100])

@external
def foo():
    pass
    """
    get_contract(loggy_code)


def test_logging_fails_with_over_three_topics(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: indexed(int128)
    arg3: indexed(int128)
    arg4: indexed(int128)

@deploy
def __init__():
    log MyLog(1, 2, 3, 4)
    """

    with tx_failed(EventDeclarationException):
        get_contract(loggy_code)


def test_logging_fails_with_duplicate_log_names(tx_failed, get_contract):
    loggy_code = """
event MyLog: pass
event MyLog: pass

@external
def foo():
    log MyLog()
    """

    with tx_failed(NamespaceCollision):
        get_contract(loggy_code)


def test_logging_fails_with_when_log_is_undeclared(tx_failed, get_contract):
    loggy_code = """

@external
def foo():
    log MyLog()
    """

    with tx_failed(UndeclaredDefinition):
        get_contract(loggy_code)


def test_logging_fails_with_topic_type_mismatch(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)

@external
def foo():
    log MyLog(self)
    """

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_logging_fails_with_data_type_mismatch(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo():
    log MyLog(self)
    """

    with tx_failed(TypeMismatch):
        get_contract(loggy_code)


def test_logging_fails_when_number_of_arguments_is_greater_than_declaration(
    tx_failed, get_contract
):
    loggy_code = """
event MyLog:
    arg1: int128

@external
def foo():
    log MyLog(1, 2)
"""
    with tx_failed(ArgumentException):
        get_contract(loggy_code)


def test_logging_fails_when_number_of_arguments_is_less_than_declaration(tx_failed, get_contract):
    loggy_code = """
event MyLog:
    arg1: int128
    arg2: int128

@external
def foo():
    log MyLog(1)
"""
    with tx_failed(ArgumentException):
        get_contract(loggy_code)


def test_loggy_code(get_logs, get_contract):
    loggy_code = """
s: Bytes[100]

@external
def foo():
    raw_log([], b"moo")

@external
def goo():
    raw_log([0x1234567812345678123456781234567812345678123456781234567812345678], b"moo2")

@external
def hoo():
    self.s = b"moo3"
    raw_log([], self.s)

@external
def ioo(inp: Bytes[100]):
    raw_log([], inp)
    """

    c = get_contract(loggy_code)

    c.foo()
    ((topics, data),) = get_logs(c, raw=True)

    assert to_text(data) == "moo"
    c.goo()
    ((topics, data),) = get_logs(c, raw=True)

    assert to_text(data) == "moo2"
    assert topics[0] == bytes.fromhex(
        "1234567812345678123456781234567812345678123456781234567812345678"
    )

    c.hoo()
    ((topics, data),) = get_logs(c, raw=True)
    assert to_text(data) == "moo3"

    c.ioo(b"moo4")
    ((topics, data),) = get_logs(c, raw=True)
    assert to_text(data) == "moo4"

    print("Passed raw log tests")


def test_raw_call_bytes32_data(get_logs, get_contract):
    code = """
b: uint256

@external
def foo():
    a: uint256 = 1234
    self.b = 4321
    raw_log([], convert(a, bytes32))
    raw_log([], convert(self.b, bytes32))
    raw_log([], convert(b"testmessage", bytes32))
    raw_log([], keccak256(b""))
    """
    c = get_contract(code)
    c.foo()
    logs = get_logs(c, raw=True)
    assert logs[0][1] == (1234).to_bytes(32, "big")
    assert logs[1][1] == (4321).to_bytes(32, "big")
    assert logs[2][1] == b"testmessage".ljust(32, b"\0")
    assert logs[3][1] == keccak256(b"")


def test_variable_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: int128[4]

@external
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log Bar(a)
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [1, 2, 3, 4]


def test_literal_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: int128[4]

@external
def foo():
    log Bar([1, 2, 3, 4])
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [1, 2, 3, 4]


def test_storage_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: int128[4]

x: int128[4]

@external
def foo():
    log Bar(self.x)

@external
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [0, 0, 0, 0]
    c.set_list()
    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [1, 2, 3, 4]


def test_passed_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: int128[4]

@external
def foo(barbaric: int128[4]):
    log Bar(barbaric)
    """
    c = get_contract(code)

    c.foo([4, 5, 6, 7])
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [4, 5, 6, 7]


def test_variable_decimal_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: decimal[4]

@external
def foo():
    log Bar([1.11, 2.22, 3.33, 4.44])
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [
        decimal_to_int("1.11"),
        decimal_to_int("2.22"),
        decimal_to_int("3.33"),
        decimal_to_int("4.44"),
    ]


def test_storage_byte_packing(get_logs, get_contract):
    code = """
event MyLog:
    arg1: Bytes[29]

x:Bytes[5]

@external
def foo(a: int128):
    log MyLog(self.x)

@external
def setbytez():
    self.x = b'hello'
    """

    c = get_contract(code)
    c.foo(0)
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == b""
    c.setbytez()
    c.foo(0)
    (log,) = get_logs(c, "MyLog")
    assert log.args.arg1 == b"hello"


def test_storage_decimal_list_packing(get_logs, get_contract):
    code = """
event Bar:
    _value: decimal[4]

x: decimal[4]

@external
def foo():
    log Bar(self.x)

@external
def set_list():
    self.x = [1.33, 2.33, 3.33, 4.33]
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [decimal_to_int("0")] * 4
    c.set_list()
    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args._value == [
        decimal_to_int("1.33"),
        decimal_to_int("2.33"),
        decimal_to_int("3.33"),
        decimal_to_int("4.33"),
    ]


def test_logging_fails_when_input_is_too_big(tx_failed, get_contract):
    code = """
event Bar:
    _value: indexed(Bytes[32])

@external
def foo(inp: Bytes[33]):
    log Bar(inp)
"""
    with tx_failed(TypeMismatch):
        get_contract(code)


def test_2nd_var_list_packing(get_logs, get_contract):
    code = """
event Bar:
    arg1: int128
    arg2: int128[4]

@external
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log Bar(10, a)
    """
    c = get_contract(code)

    c.foo()
    assert get_logs(c, "Bar")[0].args.arg2 == [1, 2, 3, 4]


def test_2nd_var_storage_list_packing(get_logs, get_contract):
    code = """
event Bar:
    arg1: int128
    arg2: int128[4]

x: int128[4]

@external
def foo():
    log Bar(10, self.x)

@external
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract(code)

    c.foo()
    assert get_logs(c, "Bar")[0].args.arg2 == [0, 0, 0, 0]
    c.set_list()
    c.foo()
    assert get_logs(c, "Bar")[0].args.arg2 == [1, 2, 3, 4]


def test_mixed_var_list_packing(get_logs, get_contract):
    code = """
event Bar:
    arg1: int128
    arg2: int128[4]
    arg3 :Bytes[4]
    arg4: int128[3]
    arg5: int128[2]

x: int128[4]
y: int128[2]

@deploy
def __init__():
    self.y = [1024, 2048]

@external
def foo():
    v: int128[3] = [7, 8, 9]
    log Bar(10, self.x, b"test", v, self.y)

@external
def set_list():
    self.x = [1, 2, 3, 4]
    """
    c = get_contract(code)

    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args.arg2 == [0, 0, 0, 0]
    assert log.args.arg3 == b"test"
    assert log.args.arg4 == [7, 8, 9]
    assert log.args.arg5 == [1024, 2048]

    c.set_list()
    c.foo()
    (log,) = get_logs(c, "Bar")
    assert log.args.arg2 == [1, 2, 3, 4]
    assert log.args.arg3 == b"test"
    assert log.args.arg4 == [7, 8, 9]
    assert log.args.arg5 == [1024, 2048]


def test_hashed_indexed_topics_calldata(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[36])
    arg2: indexed(int128)
    arg3: indexed(String[7])

@external
def foo(a: Bytes[36], b: int128, c: String[7]):
    log MyLog(a, b, c)
    """

    c = get_contract(loggy_code)
    c.foo(b"bar", 1, "weird")

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    topic1 = keccak256(b"bar")
    topic2 = abi.encode("int128", 1)
    topic3 = keccak256(b"weird")

    (log,) = get_logs(c)
    assert log.topics == [event_id, topic1, topic2, topic3]

    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_memory(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[10])
    arg2: indexed(int128)
    arg3: indexed(String[44])

@external
def foo():
    a: Bytes[10] = b"potato"
    b: int128 = -777
    c: String[44] = "why hello, neighbor! how are you today?"
    log MyLog(a, b, c)
    """

    c = get_contract(loggy_code)
    c.foo()

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    topic1 = keccak256(b"potato")
    topic2 = abi.encode("int128", -777)
    topic3 = keccak256(b"why hello, neighbor! how are you today?")
    (log,) = get_logs(c)
    assert log.topics == [event_id, topic1, topic2, topic3]

    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_storage(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[32])
    arg2: indexed(int128)
    arg3: indexed(String[6])

a: Bytes[32]
b: int128
c: String[6]


@external
def setter(_a: Bytes[32], _b: int128, _c: String[6]):
    self.a = _a
    self.b = _b
    self.c = _c

@external
def foo():
    log MyLog(self.a, self.b, self.c)
    """

    c = get_contract(loggy_code)
    c.setter(b"zonk", -2109, "yessir")
    c.foo()

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    topic1 = keccak256(b"zonk")
    topic2 = abi.encode("int128", -2109)
    topic3 = keccak256(b"yessir")

    (log,) = get_logs(c)
    assert log.topics == [event_id, topic1, topic2, topic3]

    # Event abi is created correctly
    assert c.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_storxxage(get_logs, keccak, get_contract):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[64])
    arg2: indexed(int128)
    arg3: indexed(String[21])

@external
def foo():
    log MyLog(b"wow", 666, "madness!")
    """

    c = get_contract(loggy_code)
    c.foo()

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    topic1 = keccak256(b"wow")
    topic2 = abi.encode("int128", 666)
    topic3 = keccak256(b"madness!")

    (log,) = get_logs(c)
    assert log.topics == [event_id, topic1, topic2, topic3]


fail_list = [
    (
        """
@external
def foo():
    raw_log([1, 2], b"moo")
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    raw_log([1, 2], b"moo")
    """,
        TypeMismatch,
    ),
    (
        """
@external
def foo():
    a: DynArray[bytes32, 1] = [0x1234567812345678123456781234567812345678123456781234567812345678]
    raw_log(a, b"moo2")
    """,
        InvalidType,
    ),
    (
        """
@external
def foo():
    raw_log([b"cow"], b"dog")
    """,
        (StructureException, TypeMismatch),
    ),
    (
        """
@external
def foo():
    # bytes20 instead of bytes32
    raw_log([], 0x1234567890123456789012345678901234567890)
    """,
        TypeMismatch,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_raw_log_fail(get_contract, bad_code, exc, assert_compile_failed):
    assert_compile_failed(lambda: get_contract(bad_code), exc)
