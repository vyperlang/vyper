from decimal import Decimal

import pytest
from eth.codecs import abi

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

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_empty_event_logging(w3, tester, keccak, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog: pass

@external
def foo():
    log MyLog()
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog()", "utf-8"))

    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [],
        "anonymous": False,
        "type": "event",
    }
    # Event is decoded correctly
    assert hasattr(c._classic_contract.events, "MyLog")


def test_event_logging_with_topics(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """

a: Bytes[3]

event MyLog:
    arg1: indexed(Bytes[3])

@external
def foo():
    self.a = b"bar"
    log MyLog(self.a)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))

    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [{"type": "bytes", "name": "arg1", "indexed": True}],
        "anonymous": False,
        "type": "event",
    }


def test_event_logging_with_multiple_topics(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: indexed(bool)
    arg3: indexed(address)

@external
def foo():
    log MyLog(-2, True, self)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(int128,bool,address)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
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
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].event == "MyLog"
    assert logs[0].args.arg1 == -2
    assert logs[0].args.arg2 is True
    assert logs[0].args.arg3 == c._classic_contract.address


def test_event_logging_with_multiple_topics_var_and_store(
    tester, get_contract_with_gas_estimation, get_logs
):
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

    c = get_contract_with_gas_estimation(code)
    tx_hash = c.foo(31337, transact={})

    # Event is decoded correctly
    log = get_logs(tx_hash, c, "MyLog")[0]

    assert log.args.arg1 == 31337
    assert log.args.arg2 is True
    assert log.args.arg3 == c.address


def test_logging_the_same_event_multiple_times_with_topics(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
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

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash1 = c.foo(transact={})
    tx_hash2 = c.bar(transact={})
    receipt1 = tester.get_transaction_receipt(tx_hash1.hex())
    receipt2 = tester.get_transaction_receipt(tx_hash2.hex())

    event_id = keccak(bytes("MyLog(int128,address)", "utf-8"))
    # Event id is always the first topic
    assert receipt1["logs"][0]["topics"][0] == event_id.hex()
    assert receipt2["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": True},
            {"type": "address", "name": "arg2", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    logs = get_logs(tx_hash1, c, "MyLog")
    assert logs[0].args.arg1 == 1
    assert logs[0].args.arg2 == c.address
    assert logs[1].args.arg1 == 1
    assert logs[1].args.arg2 == c.address


def test_event_logging_cannot_have_more_than_three_topics(
    tx_failed, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])
    arg2: indexed(Bytes[4])
    arg3: indexed(address)
    arg4: indexed(int128)
    """

    with pytest.raises(EventDeclarationException):
        compile_code(loggy_code)


def test_event_logging_with_data(w3, tester, keccak, get_logs, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: int128

@external
def foo():
    log MyLog(123)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(int128)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [{"type": "int128", "name": "arg1", "indexed": False}],
        "anonymous": False,
        "type": "event",
    }

    # Event is decoded correctly
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].args.arg1 == 123


def test_event_logging_with_fixed_array_data(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
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

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(int128[2],uint256[3],int128[2][2])", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly

    assert c._classic_contract.abi[0] == {
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
    timestamp = w3.eth.get_block(w3.eth.block_number).timestamp
    logs = get_logs(tx_hash, c, "MyLog")

    assert logs[0].args.arg1 == [1, 2]
    assert logs[0].args.arg2 == [timestamp, timestamp + 1, timestamp + 2]
    assert logs[0].args.arg3 == [[1, 2], [1, 2]]


def test_logging_with_input_bytes_1(
    w3, tester, keccak, get_logs, bytes_helper, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: Bytes[4]
    arg2: indexed(Bytes[29])
    arg3: Bytes[31]

@external
def foo(arg1: Bytes[29], arg2: Bytes[31]):
    log MyLog(b'bar', arg1, arg2)
"""

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(b"bar", b"foo", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(bytes,bytes,bytes)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
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
    logs = get_logs(tx_hash, c, "MyLog")

    assert logs[0].args.arg1 == b"bar"
    assert logs[0].args.arg2 == keccak(b"bar")
    assert logs[0].args.arg3 == b"foo"


def test_event_logging_with_bytes_input_2(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: Bytes[20]

@external
def foo(_arg1: Bytes[20]):
    log MyLog(_arg1)
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(b"hello", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "anonymous": False,
        "inputs": [{"indexed": False, "name": "arg1", "type": "bytes"}],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].args.arg1 == b"hello"


def test_event_logging_with_bytes_input_3(w3, tester, keccak, get_logs, get_contract):
    loggy_code = """
event MyLog:
    arg1: Bytes[5]

@external
def foo(_arg1: Bytes[5]):
    log MyLog(_arg1)
    """

    c = get_contract(loggy_code)
    tx_hash = c.foo(b"hello", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(bytes)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "anonymous": False,
        "inputs": [{"indexed": False, "name": "arg1", "type": "bytes"}],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].args.arg1 == b"hello"


def test_event_logging_with_data_with_different_types(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
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

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(int128,bytes,bytes,address,address,uint256)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
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
    timestamp = w3.eth.get_block(w3.eth.block_number).timestamp
    logs = get_logs(tx_hash, c, "MyLog")
    args = logs[0].args
    assert args.arg1 == 123
    assert args.arg2 == b"home"
    assert args.arg3 == b"bar"
    assert args.arg4 == "0xc305c901078781C232A2a521C2aF7980f8385ee9"
    assert args.arg5 == c.address
    assert args.arg6 == timestamp


def test_event_logging_with_topics_and_data_1(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)
    arg2: Bytes[3]

@external
def foo():
    log MyLog(1, b'bar')
    """

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    event_id = keccak(bytes("MyLog(int128,bytes)", "utf-8"))
    # Event id is always the first topic
    assert receipt["logs"][0]["topics"][0] == event_id.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "name": "arg1", "type": "int128"},
            {"indexed": False, "name": "arg2", "type": "bytes"},
        ],
        "name": "MyLog",
        "type": "event",
    }
    # Event is decoded correctly
    logs = get_logs(tx_hash, c, "MyLog")
    args = logs[0].args
    assert args.arg1 == 1
    assert args.arg2 == b"bar"


def test_event_logging_with_multiple_logs_topics_and_data(
    w3, tester, keccak, get_logs, get_contract_with_gas_estimation
):
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

    c = get_contract_with_gas_estimation(loggy_code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    logs1 = receipt["logs"][0]
    logs2 = receipt["logs"][1]
    event_id1 = keccak(bytes("MyLog(int128,bytes)", "utf-8"))
    event_id2 = keccak(bytes("YourLog(address,(uint256,bytes,(string,fixed168x10)))", "utf-8"))

    # Event id is always the first topic
    assert logs1["topics"][0] == event_id1.hex()
    assert logs2["topics"][0] == event_id2.hex()
    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "int128", "name": "arg1", "indexed": True},
            {"type": "bytes", "name": "arg2", "indexed": False},
        ],
        "anonymous": False,
        "type": "event",
    }
    assert c._classic_contract.abi[1] == {
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
                            {"name": "w", "type": "fixed168x10"},
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
    logs = get_logs(tx_hash, c, "MyLog")
    args = logs[0].args
    assert args.arg1 == 1
    assert args.arg2 == b"bar"
    logs = get_logs(tx_hash, c, "YourLog")
    args = logs[0].args
    assert args.arg1 == c.address
    assert args.arg2 == {"x": 1, "y": b"abc", "z": {"t": "house", "w": Decimal("13.5")}}


def test_fails_when_input_is_the_wrong_type(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)

@external
def foo_():
    log MyLog(b'yo')
"""

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_fails_when_topic_is_the_wrong_size(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])


@external
def foo():
    log MyLog(b'bars')
"""

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_fails_when_input_topic_is_the_wrong_size(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[3])

@external
def foo(arg1: Bytes[4]):
    log MyLog(arg1)
"""

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_fails_when_data_is_the_wrong_size(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo():
    log MyLog(b'bars')
"""

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_fails_when_input_data_is_the_wrong_size(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo(arg1: Bytes[4]):
    log MyLog(arg1)
"""

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_topic_over_32_bytes(get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: indexed(Bytes[100])

@external
def foo():
    pass
    """
    get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_with_over_three_topics(tx_failed, get_contract_with_gas_estimation):
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
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_with_duplicate_log_names(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog: pass
event MyLog: pass

@external
def foo():
    log MyLog()
    """

    with tx_failed(NamespaceCollision):
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_with_when_log_is_undeclared(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """

@external
def foo():
    log MyLog()
    """

    with tx_failed(UndeclaredDefinition):
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_with_topic_type_mismatch(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: indexed(int128)

@external
def foo():
    log MyLog(self)
    """

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_with_data_type_mismatch(tx_failed, get_contract_with_gas_estimation):
    loggy_code = """
event MyLog:
    arg1: Bytes[3]

@external
def foo():
    log MyLog(self)
    """

    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_when_number_of_arguments_is_greater_than_declaration(
    tx_failed, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: int128

@external
def foo():
    log MyLog(1, 2)
"""
    with tx_failed(ArgumentException):
        get_contract_with_gas_estimation(loggy_code)


def test_logging_fails_when_number_of_arguments_is_less_than_declaration(
    tx_failed, get_contract_with_gas_estimation
):
    loggy_code = """
event MyLog:
    arg1: int128
    arg2: int128

@external
def foo():
    log MyLog(1)
"""
    with tx_failed(ArgumentException):
        get_contract_with_gas_estimation(loggy_code)


def test_loggy_code(w3, tester, get_contract_with_gas_estimation):
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

    c = get_contract_with_gas_estimation(loggy_code)

    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt["logs"]

    assert w3.to_text(logs[0]["data"]) == "moo"
    tx_hash = c.goo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt["logs"]
    assert w3.to_text(logs[0]["data"]) == "moo2"
    assert (
        logs[0]["topics"][0] == "0x1234567812345678123456781234567812345678123456781234567812345678"
    )  # noqa: E501

    tx_hash = c.hoo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt["logs"]
    assert w3.to_text(logs[0]["data"]) == "moo3"

    tx_hash = c.ioo(b"moo4", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt["logs"]
    assert w3.to_text(logs[0]["data"]) == "moo4"

    print("Passed raw log tests")


def test_raw_call_bytes32_data(w3, tester, get_contract_with_gas_estimation):
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
    c = get_contract_with_gas_estimation(code)
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())
    logs = receipt["logs"]
    assert logs[0]["data"] == w3.to_hex((1234).to_bytes(32, "big"))
    assert logs[1]["data"] == w3.to_hex((4321).to_bytes(32, "big"))
    assert logs[2]["data"] == w3.to_hex(b"testmessage").ljust(32 * 2 + 2, "0")
    assert logs[3]["data"] == w3.to_hex(keccak256(b""))


def test_variable_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
event Bar:
    _value: int128[4]

@external
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log Bar(a)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [1, 2, 3, 4]


def test_literal_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
event Bar:
    _value: int128[4]

@external
def foo():
    log Bar([1, 2, 3, 4])
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [1, 2, 3, 4]


def test_storage_list_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):
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
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [0, 0, 0, 0]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [1, 2, 3, 4]


def test_passed_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
event Bar:
    _value: int128[4]

@external
def foo(barbaric: int128[4]):
    log Bar(barbaric)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo([4, 5, 6, 7], transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [4, 5, 6, 7]


def test_variable_decimal_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
event Bar:
    _value: decimal[4]

@external
def foo():
    log Bar([1.11, 2.22, 3.33, 4.44])
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [
        Decimal("1.11"),
        Decimal("2.22"),
        Decimal("3.33"),
        Decimal("4.44"),
    ]


def test_storage_byte_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):
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

    c = get_contract_with_gas_estimation(code)
    tx_hash = c.foo(0, transact={})
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].args.arg1 == b""
    c.setbytez(transact={})
    tx_hash = c.foo(0, transact={})
    logs = get_logs(tx_hash, c, "MyLog")
    assert logs[0].args.arg1 == b"hello"


def test_storage_decimal_list_packing(get_logs, bytes_helper, get_contract_with_gas_estimation):
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
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    logs = get_logs(tx_hash, c, "Bar")
    assert logs[0].args._value == [
        Decimal("1.33"),
        Decimal("2.33"),
        Decimal("3.33"),
        Decimal("4.33"),
    ]


def test_logging_fails_when_input_is_too_big(tx_failed, get_contract_with_gas_estimation):
    code = """
event Bar:
    _value: indexed(Bytes[32])

@external
def foo(inp: Bytes[33]):
    log Bar(inp)
"""
    with tx_failed(TypeMismatch):
        get_contract_with_gas_estimation(code)


def test_2nd_var_list_packing(get_logs, get_contract_with_gas_estimation):
    code = """
event Bar:
    arg1: int128
    arg2: int128[4]

@external
def foo():
    a: int128[4] = [1, 2, 3, 4]
    log Bar(10, a)
    """
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, "Bar")[0].args.arg2 == [1, 2, 3, 4]


def test_2nd_var_storage_list_packing(get_logs, get_contract_with_gas_estimation):
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
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, "Bar")[0].args.arg2 == [0, 0, 0, 0]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    assert get_logs(tx_hash, c, "Bar")[0].args.arg2 == [1, 2, 3, 4]


def test_mixed_var_list_packing(get_logs, get_contract_with_gas_estimation):
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
    c = get_contract_with_gas_estimation(code)

    tx_hash = c.foo(transact={})
    log = get_logs(tx_hash, c, "Bar")[0]
    assert log.args["arg2"] == [0, 0, 0, 0]
    assert log.args["arg3"] == b"test"
    assert log.args["arg4"] == [7, 8, 9]
    assert log.args["arg5"] == [1024, 2048]
    c.set_list(transact={})
    tx_hash = c.foo(transact={})
    log = get_logs(tx_hash, c, "Bar")[0]
    assert log.args["arg2"] == [1, 2, 3, 4]
    assert log.args["arg3"] == b"test"
    assert log.args["arg4"] == [7, 8, 9]
    assert log.args["arg5"] == [1024, 2048]


def test_hashed_indexed_topics_calldata(tester, keccak, get_contract):
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
    tx_hash = c.foo(b"bar", 1, "weird", transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    assert receipt["logs"][0]["topics"][0] == event_id.hex()

    topic1 = f"0x{keccak256(b'bar').hex()}"
    assert receipt["logs"][0]["topics"][1] == topic1

    topic2 = f"0x{abi.encode('int128', 1).hex()}"
    assert receipt["logs"][0]["topics"][2] == topic2

    topic3 = f"0x{keccak256(b'weird').hex()}"
    assert receipt["logs"][0]["topics"][3] == topic3

    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_memory(tester, keccak, get_contract):
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
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    assert receipt["logs"][0]["topics"][0] == event_id.hex()

    topic1 = f"0x{keccak256(b'potato').hex()}"
    assert receipt["logs"][0]["topics"][1] == topic1

    topic2 = f"0x{abi.encode('int128', -777).hex()}"
    assert receipt["logs"][0]["topics"][2] == topic2

    topic3 = f"0x{keccak256(b'why hello, neighbor! how are you today?').hex()}"
    assert receipt["logs"][0]["topics"][3] == topic3

    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_storage(tester, keccak, get_contract):
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
    c.setter(b"zonk", -2109, "yessir", transact={})
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    assert receipt["logs"][0]["topics"][0] == event_id.hex()

    topic1 = f"0x{keccak256(b'zonk').hex()}"
    assert receipt["logs"][0]["topics"][1] == topic1

    topic2 = f"0x{abi.encode('int128', -2109).hex()}"
    assert receipt["logs"][0]["topics"][2] == topic2

    topic3 = f"0x{keccak256(b'yessir').hex()}"
    assert receipt["logs"][0]["topics"][3] == topic3

    # Event abi is created correctly
    assert c._classic_contract.abi[0] == {
        "name": "MyLog",
        "inputs": [
            {"type": "bytes", "name": "arg1", "indexed": True},
            {"type": "int128", "name": "arg2", "indexed": True},
            {"type": "string", "name": "arg3", "indexed": True},
        ],
        "anonymous": False,
        "type": "event",
    }


def test_hashed_indexed_topics_storxxage(tester, keccak, get_contract):
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
    tx_hash = c.foo(transact={})
    receipt = tester.get_transaction_receipt(tx_hash.hex())

    # Event id is always the first topic
    event_id = keccak(b"MyLog(bytes,int128,string)")
    assert receipt["logs"][0]["topics"][0] == event_id.hex()

    topic1 = f"0x{keccak256(b'wow').hex()}"
    assert receipt["logs"][0]["topics"][1] == topic1

    topic2 = f"0x{abi.encode('int128', 666).hex()}"
    assert receipt["logs"][0]["topics"][2] == topic2

    topic3 = f"0x{keccak256(b'madness!').hex()}"
    assert receipt["logs"][0]["topics"][3] == topic3


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
def test_raw_log_fail(get_contract_with_gas_estimation, bad_code, exc, assert_compile_failed):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(bad_code), exc)
