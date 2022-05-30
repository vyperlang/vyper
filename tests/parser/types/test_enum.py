import itertools as it

import pytest

from vyper.codegen.types import parse_integer_typeinfo


def test_values_should_be_increasing_ints(get_contract):
    code = """
enum Action:
    buy
    sell

@external
@view
def buy() -> Action:
    return Action.buy

@external
@view
def sell() -> Action:
    return Action.sell
    
    """
    c = get_contract(code)
    assert c.buy() == 1
    assert c.sell() == 2
