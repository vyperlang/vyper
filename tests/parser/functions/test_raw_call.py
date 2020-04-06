from vyper.functions import (
    get_create_forwarder_to_bytecode,
)


def test_caller_code(get_contract_with_gas_estimation):
    caller_code = """
@public
def foo() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", gas=50000, outsize=5)

@public
def bar() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", gas=50000, outsize=3)

@public
def baz() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, b"moose", gas=50000, outsize=7)
    """

    c = get_contract_with_gas_estimation(caller_code)
    assert c.foo() == b"moose"
    assert c.bar() == b"moo"
    assert c.baz() == b"moose\x00\x00"

    print('Passed raw call test')


def test_multiple_levels(w3, get_contract_with_gas_estimation):
    inner_code = """
@public
def returnten() -> int128:
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@public
def create_and_call_returnten(inp: address) -> int128:
    x: address = create_forwarder_to(inp)
    o: int128 = extract32(raw_call(x, convert("\xd0\x1f\xb1\xb8", bytes[4]), outsize=32, gas=50000), 0, type=int128)  # noqa: E501
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    x: address = create_forwarder_to(inp)
    return x
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    c2.create_and_call_returnten(c.address, transact={})

    expected_forwarder_code_mask = get_create_forwarder_to_bytecode()[12:]

    c3 = c2.create_and_return_forwarder(c.address, call={})
    c2.create_and_return_forwarder(c.address, transact={})

    c3_contract_code = w3.toBytes(w3.eth.getCode(c3))

    assert c3_contract_code[:14] == expected_forwarder_code_mask[:14]
    assert c3_contract_code[35:] == expected_forwarder_code_mask[35:]

    print('Passed forwarder test')
    # TODO: This one is special
    # print(f'Gas consumed: {(chain.head_state.receipts[-1].gas_used - chain.head_state.receipts[-2].gas_used - chain.last_tx.intrinsic_gas_used)}')  # noqa: E501


def test_multiple_levels2(assert_tx_failed, get_contract_with_gas_estimation):
    inner_code = """
@public
def returnten() -> int128:
    assert False
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@public
def create_and_call_returnten(inp: address) -> int128:
    x: address = create_forwarder_to(inp)
    o: int128 = extract32(raw_call(x, convert("\xd0\x1f\xb1\xb8", bytes[4]), outsize=32, gas=50000), 0, type=int128)  # noqa: E501
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    return create_forwarder_to(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)

    assert_tx_failed(lambda: c2.create_and_call_returnten(c.address))

    print('Passed forwarder exception test')


def test_delegate_call(w3, get_contract):
    inner_code = """
a: address  # this is required for storage alignment...
owners: public(address[5])

@public
def set_owner(i: int128, o: address):
    self.owners[i] = o
    """

    inner_contract = get_contract(inner_code)

    outer_code = """
owner_setter_contract: public(address)
owners: public(address[5])


@public
def __init__(_owner_setter: address):
    self.owner_setter_contract = _owner_setter


@public
def set(i: int128, owner: address):
    # delegate setting owners to other contract.s
    cdata: bytes[68] = concat(method_id("set_owner(int128,address)", bytes[4]), convert(i, bytes32), convert(owner, bytes32))  # noqa: E501
    raw_call(
        self.owner_setter_contract,
        cdata,
        gas=msg.gas,
        outsize=0,
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
    assert w3.eth.getTransactionReceipt(tx_hash)['status'] == 1
    assert outer_contract.owners(1) == a1


def test_gas(get_contract, assert_tx_failed):
    inner_code = """
bar: bytes32

@public
def foo(_bar: bytes32):
    self.bar = _bar
    """

    inner_contract = get_contract(inner_code)

    outer_code = """
@public
def foo_call(_addr: address):
    cdata: bytes[40] = concat(
        method_id("foo(bytes32)", bytes[4]),
        0x0000000000000000000000000000000000000000000000000000000000000001
    )
    raw_call(_addr, cdata, outsize=0{})
    """

    # with no gas value given, enough will be forwarded to complete the call
    outer_contract = get_contract(outer_code.format(""))
    outer_contract.foo_call(inner_contract.address)

    # manually specifying a sufficient amount should succeed
    outer_contract = get_contract(outer_code.format(", gas=21000"))
    outer_contract.foo_call(inner_contract.address)

    # manually specifying an insufficient amount should fail
    outer_contract = get_contract(outer_code.format(", gas=15000"))
    assert_tx_failed(lambda: outer_contract.foo_call(inner_contract.address))
