import pytest
from tests.setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_caller_code():
    caller_code = """
@public
def foo() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=5)

@public
def bar() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=3)

@public
def baz() -> bytes <= 7:
    return raw_call(0x0000000000000000000000000000000000000004, "moose", gas=50000, outsize=7)
    """

    c = get_contract_with_gas_estimation(caller_code)
    assert c.foo() == b"moose"
    assert c.bar() == b"moo"
    assert c.baz() == b"moose\x00\x00"

    print('Passed raw call test')



def test_multiple_levels():
    inner_code = """
@public
def returnten() -> num:
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@public
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    x = create_with_code_of(inp)
    return x
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    assert c2.create_and_call_returnten(c.address) == 10
    expected_forwarder_code_mask = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'[12:]
    c3 = c2.create_and_return_forwarder(c.address)
    assert s.head_state.get_code(c3)[:15] == expected_forwarder_code_mask[:15]
    assert s.head_state.get_code(c3)[35:] == expected_forwarder_code_mask[35:]

    print('Passed forwarder test')
    # TODO: This one is special
    print('Gas consumed: %d' % (s.head_state.receipts[-1].gas_used - s.head_state.receipts[-2].gas_used - s.last_tx.intrinsic_gas_used))


def test_multiple_levels2():
    inner_code = """
@public
def returnten() -> num:
    assert False
    return 10
    """

    c = get_contract_with_gas_estimation(inner_code)

    outer_code = """
@public
def create_and_call_returnten(inp: address) -> num:
    x = create_with_code_of(inp)
    o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
    return o

@public
def create_and_return_forwarder(inp: address) -> address:
    return create_with_code_of(inp)
    """

    c2 = get_contract_with_gas_estimation(outer_code)
    try:
        c2.create_and_call_returnten(c.address)
        success = True
    except:
        success = False
    assert not success

    print('Passed forwarder exception test')
