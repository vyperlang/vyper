"""
Tests for event logging in Venom codegen.

Events are emitted via LOG0-LOG4 opcodes with:
- topic0: Event signature hash (keccak256 of signature)
- topic1-3: Indexed parameters (up to 3)
- data: Non-indexed parameters, ABI-encoded
"""

import pytest

from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings


def _compile_experimental(source: str) -> bytes:
    """Compile source with experimental codegen and return bytecode."""
    settings = Settings(experimental_codegen=True)
    return CompilerData(source, settings=settings).bytecode_runtime


class TestEventLogging:
    """Test event logging (Log statement) codegen."""

    def test_simple_event(self):
        """Test basic event with non-indexed params."""
        source = """
event Transfer:
    sender: address
    receiver: address
    amount: uint256

@external
def emit_transfer(sender: address, receiver: address, amount: uint256):
    log Transfer(sender, receiver, amount)
        """
        _compile_experimental(source)

    def test_event_with_indexed(self):
        """Test event with indexed parameters."""
        source = """
event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    amount: uint256

@external
def emit_transfer(sender: address, receiver: address, amount: uint256):
    log Transfer(sender, receiver, amount)
        """
        _compile_experimental(source)

    def test_event_all_indexed(self):
        """Test event with all indexed parameters (max 3)."""
        source = """
event Approval:
    owner: indexed(address)
    spender: indexed(address)
    amount: indexed(uint256)

@external
def emit_approval(owner: address, spender: address, amount: uint256):
    log Approval(owner, spender, amount)
        """
        _compile_experimental(source)

    def test_event_no_params(self):
        """Test event with no parameters."""
        source = """
event Ping:
    pass

@external
def emit_ping():
    log Ping()
        """
        _compile_experimental(source)

    def test_event_single_indexed(self):
        """Test event with single indexed parameter."""
        source = """
event Deposit:
    depositor: indexed(address)
    amount: uint256
    memo: uint256

@external
def emit_deposit(depositor: address, amount: uint256, memo: uint256):
    log Deposit(depositor, amount, memo)
        """
        _compile_experimental(source)

    def test_event_only_non_indexed(self):
        """Test event with only non-indexed parameters."""
        source = """
event DataStored:
    key: bytes32
    val: uint256
    timestamp: uint256

@external
def emit_data(key: bytes32, val: uint256, timestamp: uint256):
    log DataStored(key=key, val=val, timestamp=timestamp)
        """
        _compile_experimental(source)

    def test_event_keyword_args(self):
        """Test event with keyword arguments."""
        source = """
event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    amount: uint256

@external
def emit_transfer(sender: address, receiver: address, amount: uint256):
    log Transfer(sender=sender, receiver=receiver, amount=amount)
        """
        _compile_experimental(source)

    def test_event_with_bool(self):
        """Test event with boolean parameter."""
        source = """
event StatusChanged:
    account: indexed(address)
    active: bool

@external
def emit_status(account: address, active: bool):
    log StatusChanged(account, active)
        """
        _compile_experimental(source)

    def test_event_with_int128(self):
        """Test event with int128 parameter."""
        source = """
event ValueSet:
    key: indexed(bytes32)
    val: int128

@external
def emit_value(key: bytes32, val: int128):
    log ValueSet(key=key, val=val)
        """
        _compile_experimental(source)

    def test_event_with_bytes32(self):
        """Test event with bytes32 parameter."""
        source = """
event HashStored:
    slot: indexed(uint256)
    hash: bytes32

@external
def emit_hash(slot: uint256, hash: bytes32):
    log HashStored(slot, hash)
        """
        _compile_experimental(source)

    def test_multiple_events(self):
        """Test contract with multiple events."""
        source = """
event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    amount: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    amount: uint256

@external
def emit_transfer(sender: address, receiver: address, amount: uint256):
    log Transfer(sender, receiver, amount)

@external
def emit_approval(owner: address, spender: address, amount: uint256):
    log Approval(owner, spender, amount)
        """
        _compile_experimental(source)

    def test_event_with_literal(self):
        """Test event with literal value."""
        source = """
event Fixed:
    value: uint256

@external
def emit_fixed():
    log Fixed(42)
        """
        _compile_experimental(source)

    def test_event_with_expression(self):
        """Test event with computed expression."""
        source = """
event Result:
    value: uint256

@external
def emit_result(a: uint256, b: uint256):
    log Result(a + b)
        """
        _compile_experimental(source)

    def test_event_in_conditional(self):
        """Test event inside conditional."""
        source = """
event TransferWithCheck:
    sender: indexed(address)
    amount: uint256

@external
def emit_if_positive(sender: address, amount: uint256):
    if amount > 0:
        log TransferWithCheck(sender, amount)
        """
        _compile_experimental(source)

    def test_event_in_loop(self):
        """Test event inside loop."""
        source = """
event Tick:
    counter: uint256

@external
def emit_ticks(count: uint256):
    for i: uint256 in range(10):
        if i >= count:
            break
        log Tick(i)
        """
        _compile_experimental(source)


class TestEventIndexedTypes:
    """Test indexed parameter type handling."""

    def test_indexed_address(self):
        """Test indexed address type."""
        source = """
event AddressEvent:
    addr: indexed(address)

@external
def emit_addr(addr: address):
    log AddressEvent(addr)
        """
        _compile_experimental(source)

    def test_indexed_uint256(self):
        """Test indexed uint256 type."""
        source = """
event UintEvent:
    val: indexed(uint256)

@external
def emit_uint(val: uint256):
    log UintEvent(val=val)
        """
        _compile_experimental(source)

    def test_indexed_bytes32(self):
        """Test indexed bytes32 type."""
        source = """
event Bytes32Event:
    hash: indexed(bytes32)

@external
def emit_hash(hash: bytes32):
    log Bytes32Event(hash)
        """
        _compile_experimental(source)

    def test_indexed_bool(self):
        """Test indexed bool type."""
        source = """
event BoolEvent:
    flag: indexed(bool)

@external
def emit_bool(flag: bool):
    log BoolEvent(flag)
        """
        _compile_experimental(source)

    def test_indexed_int128(self):
        """Test indexed int128 type."""
        source = """
event IntEvent:
    val: indexed(int128)

@external
def emit_int(val: int128):
    log IntEvent(val=val)
        """
        _compile_experimental(source)


class TestEventDataTypes:
    """Test non-indexed (data) parameter type handling."""

    def test_data_multiple_uint256(self):
        """Test multiple uint256 data params."""
        source = """
event MultiUint:
    a: uint256
    b: uint256
    c: uint256

@external
def emit_multi(a: uint256, b: uint256, c: uint256):
    log MultiUint(a, b, c)
        """
        _compile_experimental(source)

    def test_data_mixed_types(self):
        """Test mixed data types."""
        source = """
event MixedData:
    addr: address
    amount: uint256
    flag: bool
    val: int128

@external
def emit_mixed(addr: address, amount: uint256, flag: bool, val: int128):
    log MixedData(addr=addr, amount=amount, flag=flag, val=val)
        """
        _compile_experimental(source)

    def test_data_only_address(self):
        """Test data with only address."""
        source = """
event AddressData:
    addr: address

@external
def emit_addr(addr: address):
    log AddressData(addr)
        """
        _compile_experimental(source)

    def test_data_only_bool(self):
        """Test data with only bool."""
        source = """
event BoolData:
    flag: bool

@external
def emit_bool(flag: bool):
    log BoolData(flag)
        """
        _compile_experimental(source)
