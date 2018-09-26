

def test_caller_code(get_contract_with_gas_estimation):
    caller_code = """
@public
def foo() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=5)

@public
def bar() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=3)

@public
def baz() -> bytes[7]:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=7)
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
    x: address = create_with_code_of(inp)
    o: int128 = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=int128)
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    x: address = create_with_code_of(inp)
    return x
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    c2.create_and_call_returnten(c.address, transact={})
    expected_forwarder_code_mask = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'[12:]
    c3 = c2.create_and_return_forwarder(c.address, call={})
    c2.create_and_return_forwarder(c.address, transact={})

    c3_contract_code = w3.toBytes(w3.eth.getCode(c3))
    assert c3_contract_code[:15] == expected_forwarder_code_mask[:15]
    assert c3_contract_code[35:] == expected_forwarder_code_mask[35:]

    print('Passed forwarder test')
    # TODO: This one is special
    # print('Gas consumed: %d' % (chain.head_state.receipts[-1].gas_used - chain.head_state.receipts[-2].gas_used - chain.last_tx.intrinsic_gas_used))


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
    x: address = create_with_code_of(inp)
    o: int128 = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=int128)
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)

    assert_tx_failed(lambda: c2.create_and_call_returnten(c.address))

    print('Passed forwarder exception test')



def test_delegate_call(w3, get_contract_with_gas_estimation):
    inner_code = """
owners: public(address[5])
@public
def set_owner(i: int128, owner: address):
    assert owner != ZERO_ADDRESS
    self.owners[i] = owner
    """

    inner_contract = get_contract_with_gas_estimation(inner_code)

    outer_code = """
owner_setter: public(address)
owners: public(address[5])

def __init__(_owner_setter: address):
    self.owner_setter = _owner_setter


@public
def set(i: int128, owner: address) -> int128:
    # delegate setting owners to other contract.
    raw_call(self.owner_setter, concat(method_id("set_owner(int128,address)"), gas=msg.gas, delegate_call=True)
    """

    a0, a1 = w3.eth.accounts[:2]
    outer_contract = get_contract_with_gas_estimation(outer_code, args=[a1])

    import ipdb; ipdb.set_trace()
    assert outer_contract.owner_setter() == a1
    assert outer_contract.owners(0) is None
