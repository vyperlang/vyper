import pytest
from .setup_transaction_tests import chain as s, tester as t, ethereum_utils as u, check_gas, \
    get_contract_with_gas_estimation, get_contract


def test_external_contract_calls():
    inner_code = """
def foo(arg1: num) -> num:
    return arg1
    """

    c = get_contract(inner_code)

    outer_code = """
class Foo():
    def foo(arg1: num) -> num: pass

age: public(num)

def __init__(arg1: address, arg2: num):
    self.age = arg2

def bar(arg1: address, arg2: num) -> num:
    return Foo(arg1).foo(arg2)
    """
    c2 = get_contract(outer_code, args=[c.address, 2])
    
    assert c2.get_age() == 2
    assert c2.bar(c.address, 1) == 1
    print('Successfully executed an external contract call')

# def test_multiple_levels():
#     inner_code = """
# def returnten() -> num:
#     return 10
#     """

#     c = get_contract(inner_code)

#     outer_code = """
# def create_and_call_returnten(inp: address) -> num:
#     x = create_with_code_of(inp)
#     o = extract32(raw_call(x, "\xd0\x1f\xb1\xb8", outsize=32, gas=50000), 0, type=num128)
#     return o

# def create_and_return_forwarder(inp: address) -> address:
#     return create_with_code_of(inp)
#     """

#     c2 = get_contract(outer_code)
#     assert c2.create_and_call_returnten(c.address) == 10
#     expected_forwarder_code_mask = b'`.`\x0c`\x009`.`\x00\xf36`\x00`\x007a\x10\x00`\x006`\x00s\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00Z\xf4\x15XWa\x10\x00`\x00\xf3'[12:]
#     c3 = c2.create_and_return_forwarder(c.address)
#     assert s.head_state.get_code(c3)[:15] == expected_forwarder_code_mask[:15]
#     assert s.head_state.get_code(c3)[35:] == expected_forwarder_code_mask[35:]
