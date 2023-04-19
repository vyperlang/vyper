from decimal import Decimal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.exceptions import OverflowException, TypeMismatch, ZeroDivisionException

st_decimals = st.decimals(
    min_value=-(2**32), max_value=2**32, allow_nan=False, allow_infinity=False, places=10
)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_decimals, right=st_decimals)
@example(left=Decimal("0.9999999999"), right=Decimal("0.0000000001"))
@example(left=Decimal("0.0000000001"), right=Decimal("0.9999999999"))
@example(left=Decimal("0.9999999999"), right=Decimal("0.9999999999"))
@example(left=Decimal("0.0000000001"), right=Decimal("0.0000000001"))
@pytest.mark.parametrize("op", "+-*/%")
def test_binop_decimal(get_contract, assert_tx_failed, op, left, right):
    source = f"""
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} {op} {right}")
    old_node = vyper_ast.body[0].value
    try:
        new_node = old_node.evaluate()
        is_valid = True
    except ZeroDivisionException:
        is_valid = False

    if is_valid:
        assert contract.foo(left, right) == new_node.value
    else:
        assert_tx_failed(lambda: contract.foo(left, right))


def test_binop_pow():
    # raises because Vyper does not support decimal exponentiation
    vyper_ast = vy_ast.parse_to_ast("3.1337 ** 4.2")
    old_node = vyper_ast.body[0].value

    with pytest.raises(TypeMismatch):
        old_node.evaluate()


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(
    values=st.lists(st_decimals, min_size=2, max_size=10),
    ops=st.lists(st.sampled_from("+-*/%"), min_size=11, max_size=11),
)
def test_nested(get_contract, assert_tx_failed, values, ops):
    variables = "abcdefghij"
    input_value = ",".join(f"{i}: decimal" for i in variables[: len(values)])
    return_value = " ".join(f"{a} {b}" for a, b in zip(variables[: len(values)], ops))
    return_value = return_value.rsplit(maxsplit=1)[0]
    source = f"""
@external
def foo({input_value}) -> decimal:
    return {return_value}
    """
    contract = get_contract(source)

    literal_op = " ".join(f"{a} {b}" for a, b in zip(values, ops))
    literal_op = literal_op.rsplit(maxsplit=1)[0]
    vyper_ast = vy_ast.parse_to_ast(literal_op)
    try:
        vy_ast.folding.replace_literal_ops(vyper_ast)
        expected = vyper_ast.body[0].value.value
        is_valid = -(2**127) <= expected < 2**127
    except (OverflowException, ZeroDivisionException):
        # for overflow or division/modulus by 0, expect the contract call to revert
        is_valid = False

    if is_valid:
        assert contract.foo(*values) == expected
    else:
        assert_tx_failed(lambda: contract.foo(*values))
