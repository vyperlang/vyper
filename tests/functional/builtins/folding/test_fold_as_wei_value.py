import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold
from vyper.builtins import functions as vy_fn
from vyper.utils import SizeLimits

denoms = [x for k in vy_fn.AsWeiValue.wei_denoms.keys() for x in k]


st_decimals = st.decimals(
    min_value=0,
    max_value=SizeLimits.MAX_AST_DECIMAL,
    allow_nan=False,
    allow_infinity=False,
    places=10,
)


@pytest.mark.fuzzing
@settings(max_examples=10)
@given(value=st_decimals)
@pytest.mark.parametrize("denom", denoms)
def test_decimal(get_contract, value, denom):
    source = f"""
@external
def foo(a: decimal) -> uint256:
    return as_wei_value(a, '{denom}')
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"as_wei_value({value:.10f}, '{denom}')")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(value) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=10)
@given(value=st.integers(min_value=0, max_value=2**128))
@pytest.mark.parametrize("denom", denoms)
def test_integer(get_contract, value, denom):
    source = f"""
@external
def foo(a: uint256) -> uint256:
    return as_wei_value(a, '{denom}')
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"as_wei_value({value}, '{denom}')")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(value) == new_node.value
