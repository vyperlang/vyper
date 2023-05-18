import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast

variables = "abcdefghij"


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(values=st.lists(st.booleans(), min_size=2, max_size=10))
@pytest.mark.parametrize("comparator", ["and", "or"])
def test_boolop_simple(get_contract, values, comparator):
    input_value = ",".join(f"{i}: bool" for i in variables[: len(values)])
    return_value = f" {comparator} ".join(variables[: len(values)])

    source = f"""
@external
def foo({input_value}) -> bool:
    return {return_value}
    """
    contract = get_contract(source)

    literal_op = f" {comparator} ".join(str(i) for i in values)

    vyper_ast = vy_ast.parse_to_ast(literal_op)
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(*values) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(
    values=st.lists(st.booleans(), min_size=2, max_size=10),
    comparators=st.lists(st.sampled_from(["and", "or"]), min_size=11, max_size=11),
)
def test_boolop_nested(get_contract, values, comparators):
    input_value = ",".join(f"{i}: bool" for i in variables[: len(values)])
    return_value = " ".join(f"{a} {b}" for a, b in zip(variables[: len(values)], comparators))
    return_value = return_value.rsplit(maxsplit=1)[0]

    source = f"""
@external
def foo({input_value}) -> bool:
    return {return_value}
    """
    contract = get_contract(source)

    literal_op = " ".join(f"{a} {b}" for a, b in zip(values, comparators))
    literal_op = literal_op.rsplit(maxsplit=1)[0]

    vyper_ast = vy_ast.parse_to_ast(literal_op)
    vy_ast.folding.replace_literal_ops(vyper_ast)
    expected = vyper_ast.body[0].value.value

    assert contract.foo(*values) == expected
