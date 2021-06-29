import pytest
from hexbytes import HexBytes

from vyper import compiler
from vyper.builtin_functions import get_create_forwarder_to_bytecode
from vyper.exceptions import ArgumentException, StateAccessViolation

pytestmark = pytest.mark.usefixtures("memory_mocker")


def test_max_outsize_exceeds_returndatasize(get_contract):
    source_code = """
@external
def foo() -> Bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", max_outsize=7)
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
    x: address = create_forwarder_to(inp)
    o: int128 = extract32(raw_call(x, convert("\xd0\x1f\xb1\xb8", Bytes[4]), max_outsize=32, gas=50000), 0, output_type=int128)  # noqa: E501
    return o

@external
def create_and_return_forwarder(inp: address) -> address:
    x: address = create_forwarder_to(inp)
    return x
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    c2.create_and_call_returnten(c.address, transact={})

    _, preamble, callcode = get_create_forwarder_to_bytecode()

    c3 = c2.create_and_return_forwarder(c.address, call={})
    c2.create_and_return_forwarder(c.address, transact={})

    c3_contract_code = w3.toBytes(w3.eth.getCode(c3))

    assert c3_contract_code[:10] == HexBytes(preamble)
    assert c3_contract_code[-15:] == HexBytes(callcode)

    print("Passed forwarder test")
    # TODO: This one is special
    # print(f'Gas consumed: {(chain.head_state.receipts[-1].gas_used - chain.head_state.receipts[-2].gas_used - chain.last_tx.intrinsic_gas_used)}')  # noqa: E501


def test_multiple_levels2(assert_tx_failed, get_contract_with_gas_estimation):
    inner_code = """
@external
def returnten() -> int128:
    assert False
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@external
def create_and_call_returnten(inp: address) -> int128:
    x: address = create_forwarder_to(inp)
    o: int128 = extract32(raw_call(x, convert("\xd0\x1f\xb1\xb8", Bytes[4]), max_outsize=32, gas=50000), 0, output_type=int128)  # noqa: E501
    return o

@external
def create_and_return_forwarder(inp: address) -> address:
    return create_forwarder_to(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)

    assert_tx_failed(lambda: c2.create_and_call_returnten(c.address))

    print("Passed forwarder exception test")


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
    assert w3.eth.getTransactionReceipt(tx_hash)["status"] == 1
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
]


@pytest.mark.parametrize("source_code,exc", uncompilable_code)
def test_invalid_type_exception(source_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(source_code)
