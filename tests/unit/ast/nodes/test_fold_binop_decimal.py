from decimal import Decimal

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from tests.utils import decimal_to_int, parse_and_fold
from vyper.exceptions import OverflowException, TypeMismatch, ZeroDivisionException
from vyper.semantics.analysis.local import ExprVisitor
from vyper.semantics.types import DecimalT

DECIMAL_T = DecimalT()

st_decimals = st.decimals(
    min_value=DECIMAL_T.decimal_bounds[0],
    max_value=DECIMAL_T.decimal_bounds[1],
    allow_nan=False,
    allow_infinity=False,
    places=DECIMAL_T._decimal_places,
)


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(left=st_decimals, right=st_decimals)
@example(left=Decimal("0.9999999999"), right=Decimal("0.0000000001"))
@example(left=Decimal("0.0000000001"), right=Decimal("0.9999999999"))
@example(left=Decimal("0.9999999999"), right=Decimal("0.9999999999"))
@example(left=Decimal("0.0000000001"), right=Decimal("0.0000000001"))
@pytest.mark.parametrize("op", "+-*/%")
def test_binop_decimal(get_contract, tx_failed, op, left, right):
    source = f"""
@external
def foo(a: decimal, b: decimal) -> decimal:
    return a {op} b
    """
    contract = get_contract(source)

    try:
        vyper_ast = parse_and_fold(f"{left} {op} {right}")
        expr = vyper_ast.body[0].value

        # check invalid values
        ExprVisitor().visit(expr, DecimalT())

        new_node = expr.get_folded_value()
        is_valid = True
    except (OverflowException, ZeroDivisionException):
        is_valid = False

    left = decimal_to_int(left)
    right = decimal_to_int(right)
    if is_valid:
        assert contract.foo(left, right) == decimal_to_int(new_node.value)
    else:
        with tx_failed():
            contract.foo(left, right)


def test_binop_pow():
    # raises because Vyper does not support decimal exponentiation
    with pytest.raises(TypeMismatch):
        _ = parse_and_fold("3.1337 ** 4.2")


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    values=st.lists(st_decimals, min_size=2, max_size=10),
    ops=st.lists(st.sampled_from("+-*/%"), min_size=11, max_size=11),
)
def test_nested(get_contract, tx_failed, values, ops):
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
    try:
        vyper_ast = parse_and_fold(literal_op)
        expr = vyper_ast.body[0].value

        # check invalid intermediate values
        ExprVisitor().visit(expr, DecimalT())

        new_node = expr.get_folded_value()
        expected = new_node.value
        is_valid = True
    except (OverflowException, ZeroDivisionException):
        # for overflow or division/modulus by 0, expect the contract call to revert
        is_valid = False

    values = [decimal_to_int(v) for v in values]
    if is_valid:
        assert contract.foo(*values) == decimal_to_int(expected)
    else:
        with tx_failed():
            contract.foo(*values)
