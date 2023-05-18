import pytest
from hexbytes import HexBytes

from vyper.builtins.functions import eip1167_bytecode
from vyper.exceptions import ArgumentException, InvalidType, StateAccessViolation

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_max_outsize_exceeds_returndatasize(get_contract):
    source_code = """
@external
def foo() -> Bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", max_outsize=7)
    """
    c = get_contract(source_code)
    assert c.foo() == b"moose"


def test_raw_call_non_memory(get_contract):
    source_code = """
_foo: Bytes[5]
@external
def foo() -> Bytes[5]:
    self._foo = b"moose"
    return raw_call(0x0000000000000000000000000000000000000004, self._foo, max_outsize=5)
    """
    c = get_contract(source_code)
    assert c.foo() == b"moose"


def test_returndatasize_exceeds_max_outsize(get_contract):
    source_code = """
@external
def foo() -> Bytes[3]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", max_outsize=3)
    """
    c = get_contract(source_code)
    assert c.foo() == b"moo"


def test_returndatasize_matches_max_outsize(get_contract):
    source_code = """
@external
def foo() -> Bytes[5]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", max_outsize=5)
    """
    c = get_contract(source_code)
    assert c.foo() == b"moose"


def test_multiple_levels(w3, get_contract_with_gas_estimation):
    inner_code = """
@external
def returnten() -> int128:
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@external
def create_and_call_returnten(inp: address) -> int128:
    x: address = create_minimal_proxy_to(inp)
    o: int128 = extract32(raw_call(x, b"\\xd0\\x1f\\xb1\\xb8", max_outsize=32, gas=50000), 0, output_type=int128)  # noqa: E501
    return o

@external
def create_and_return_proxy(inp: address) -> address:
    x: address = create_minimal_proxy_to(inp)
    return x
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    c2.create_and_call_returnten(c.address, transact={})

    _, preamble, callcode = eip1167_bytecode()

    c3 = c2.create_and_return_proxy(c.address, call={})
    c2.create_and_return_proxy(c.address, transact={})

    c3_contract_code = w3.to_bytes(w3.eth.get_code(c3))

    assert c3_contract_code[:10] == HexBytes(preamble)
    assert c3_contract_code[-15:] == HexBytes(callcode)

    print("Passed proxy test")
    # TODO: This one is special
    # print(f'Gas consumed: {(chain.head_state.receipts[-1].gas_used - chain.head_state.receipts[-2].gas_used - chain.last_tx.intrinsic_gas_used)}')  # noqa: E501


def test_multiple_levels2(assert_tx_failed, get_contract_with_gas_estimation):
    inner_code = """
@external
def returnten() -> int128:
    raise
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@external
def create_and_call_returnten(inp: address) -> int128:
    x: address = create_minimal_proxy_to(inp)
    o: int128 = extract32(raw_call(x, b"\\xd0\\x1f\\xb1\\xb8", max_outsize=32, gas=50000), 0, output_type=int128)  # noqa: E501
    return o

@external
def create_and_return_proxy(inp: address) -> address:
    return create_minimal_proxy_to(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)

    assert_tx_failed(lambda: c2.create_and_call_returnten(c.address))

    print("Passed minimal proxy exception test")


def test_delegate_call(w3, get_contract):
    inner_code = """
a: address  # this is required for storage alignment...
owners: public(address[5])

@external
def set_owner(i: int128, o: address):
    self.owners[i] = o
    """

    inner_contract = get_contract(inner_code)

    outer_code = """
owner_setter_contract: public(address)
owners: public(address[5])


@external
def __init__(_owner_setter: address):
    self.owner_setter_contract = _owner_setter


@external
def set(i: int128, owner: address):
    # delegate setting owners to other contract.s
    cdata: Bytes[68] = concat(method_id("set_owner(int128,address)"), convert(i, bytes32), convert(owner, bytes32))  # noqa: E501
    raw_call(
        self.owner_setter_contract,
        cdata,
        gas=msg.gas,
        max_outsize=0,
        is_delegate_call=True
    )
    """

    a0, a1, a2 = w3.eth.accounts[:3]
    outer_contract = get_contract(outer_code, *[inner_contract.address])

    # Test setting on inners contract's state setting works.
    inner_contract.set_owner(1, a2, transact={})
    assert inner_contract.owners(1) == a2

    # Confirm outer contract's state is empty and contract to call has been set.
    assert outer_contract.owner_setter_contract() == inner_contract.address
    assert outer_contract.owners(1) is None

    # Call outer contract, that make a delegate call to inner_contract.
    tx_hash = outer_contract.set(1, a1, transact={})
    assert w3.eth.get_transaction_receipt(tx_hash)["status"] == 1
    assert outer_contract.owners(1) == a1


def test_gas(get_contract, assert_tx_failed):
    inner_code = """
bar: bytes32

@external
def foo(_bar: bytes32):
    self.bar = _bar
    """

    inner_contract = get_contract(inner_code)

    outer_code = """
@external
def foo_call(_addr: address):
    cdata: Bytes[40] = concat(
        method_id("foo(bytes32)"),
        0x0000000000000000000000000000000000000000000000000000000000000001
    )
    raw_call(_addr, cdata, max_outsize=0{})
    """

    # with no gas value given, enough will be forwarded to complete the call
    outer_contract = get_contract(outer_code.format(""))
    outer_contract.foo_call(inner_contract.address)

    # manually specifying a sufficient amount should succeed
    outer_contract = get_contract(outer_code.format(", gas=50000"))
    outer_contract.foo_call(inner_contract.address)

    # manually specifying an insufficient amount should fail
    outer_contract = get_contract(outer_code.format(", gas=15000"))
    assert_tx_failed(lambda: outer_contract.foo_call(inner_contract.address))


def test_static_call(get_contract):
    target_source = """
@external
@view
def foo() -> int128:
    return 42
"""

    caller_source = """
@external
@view
def foo(_addr: address) -> int128:
    _response: Bytes[32] = raw_call(
        _addr,
        method_id("foo()"),
        max_outsize=32,
        is_static_call=True,
    )
    return convert(_response, int128)
    """

    target = get_contract(target_source)
    caller = get_contract(caller_source)

    assert caller.foo(target.address) == 42


def test_forward_calldata(get_contract, w3, keccak):
    target_source = """
@external
def foo() -> uint256:
    return 123
    """

    caller_source = """
target: address

@external
def set_target(target: address):
    self.target = target

@external
def __default__():
    assert 123 == _abi_decode(raw_call(self.target, msg.data, max_outsize=32), uint256)
    """

    target = get_contract(target_source)

    caller = get_contract(caller_source)
    caller.set_target(target.address, transact={})

    # manually construct msg.data for `caller` contract
    sig = keccak("foo()".encode()).hex()[:10]
    w3.eth.send_transaction({"to": caller.address, "data": sig})


def test_static_call_fails_nonpayable(get_contract, assert_tx_failed):
    target_source = """
baz: int128

@external
def foo() -> int128:
    self.baz = 31337
    return self.baz
"""

    caller_source = """
@external
@view
def foo(_addr: address) -> int128:
    _response: Bytes[32] = raw_call(
        _addr,
        method_id("foo()"),
        max_outsize=32,
        is_static_call=True,
    )
    return convert(_response, int128)
    """

    target = get_contract(target_source)
    caller = get_contract(caller_source)

    assert_tx_failed(lambda: caller.foo(target.address))


def test_checkable_raw_call(get_contract, assert_tx_failed):
    target_source = """
baz: int128
@external
def fail1(should_raise: bool):
    if should_raise:
        raise "fail"

# test both paths for raw_call -
# they are different depending if callee has or doesn't have returntype
# (fail2 fails because of staticcall)
@external
def fail2(should_raise: bool) -> int128:
    if should_raise:
        self.baz = self.baz + 1
    return self.baz
"""

    caller_source = """
@external
@view
def foo(_addr: address, should_raise: bool) -> uint256:
    success: bool = True
    response: Bytes[32] = b""
    success, response = raw_call(
        _addr,
        _abi_encode(should_raise, method_id=method_id("fail1(bool)")),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False,
    )
    assert success == (not should_raise)
    return 1

@external
@view
def bar(_addr: address, should_raise: bool) -> uint256:
    success: bool = True
    response: Bytes[32] = b""
    success, response = raw_call(
        _addr,
        _abi_encode(should_raise, method_id=method_id("fail2(bool)")),
        max_outsize=32,
        is_static_call=True,
        revert_on_failure=False,
    )
    assert success == (not should_raise)
    return 2

# test max_outsize not set case
@external
@nonpayable
def baz(_addr: address, should_raise: bool) -> uint256:
    success: bool = True
    success = raw_call(
        _addr,
        _abi_encode(should_raise, method_id=method_id("fail1(bool)")),
        revert_on_failure=False,
    )
    assert success == (not should_raise)
    return 3
    """

    target = get_contract(target_source)
    caller = get_contract(caller_source)

    assert caller.foo(target.address, True) == 1
    assert caller.foo(target.address, False) == 1
    assert caller.bar(target.address, True) == 2
    assert caller.bar(target.address, False) == 2
    assert caller.baz(target.address, True) == 3
    assert caller.baz(target.address, False) == 3


uncompilable_code = [
    (
        """
@external
@view
def foo(_addr: address):
    raw_call(_addr, method_id("foo()"))
    """,
        StateAccessViolation,
    ),
    (
        """
@external
def foo(_addr: address):
    raw_call(_addr, method_id("foo()"), is_delegate_call=True, is_static_call=True)
    """,
        ArgumentException,
    ),
    (
        """
@external
@view
def foo(_addr: address):
    raw_call(_addr, 256)
    """,
        InvalidType,
    ),
]


@pytest.mark.parametrize("source_code,exc", uncompilable_code)
def test_invalid_type_exception(
    assert_compile_failed, get_contract_with_gas_estimation, source_code, exc
):
    assert_compile_failed(lambda: get_contract_with_gas_estimation(source_code), exc)
