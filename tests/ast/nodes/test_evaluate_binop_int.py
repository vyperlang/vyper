import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from vyper import ast as vy_ast
from vyper.exceptions import ZeroDivisionException

st_int32 = st.integers(min_value=-(2**32), max_value=2**32)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_int32, right=st_int32)
@example(left=1, right=1)
@example(left=1, right=-1)
@example(left=-1, right=1)
@example(left=-1, right=-1)
@pytest.mark.parametrize("op", "+-*/%")
def test_binop_int128(get_contract, assert_tx_failed, op, left, right):
    source = f"""
@external
def foo(a: int128, b: int128) -> int128:
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


st_uint64 = st.integers(min_value=0, max_value=2**64)


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st_uint64, right=st_uint64)
@pytest.mark.parametrize("op", "+-*/%")
def test_binop_uint256(get_contract, assert_tx_failed, op, left, right):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a {op} b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} {op} {right}")
    old_node = vyper_ast.body[0].value
    try:
        new_node = old_node.evaluate()
        is_valid = new_node.value >= 0
    except ZeroDivisionException:
        is_valid = False

    if is_valid:
        assert contract.foo(left, right) == new_node.value
    else:
        assert_tx_failed(lambda: contract.foo(left, right))


@pytest.mark.xfail(reason="need to implement safe exponentiation logic")
@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(left=st.integers(min_value=2, max_value=245), right=st.integers(min_value=0, max_value=16))
@example(left=0, right=0)
@example(left=0, right=1)
def test_binop_int_pow(get_contract, left, right):
    source = """
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a ** b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} ** {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@pytest.mark.fuzzing
@settings(max_examples=50, deadline=1000)
@given(
    values=st.lists(st.integers(min_value=-256, max_value=256), min_size=2, max_size=10),
    ops=st.lists(st.sampled_from("+-*/%"), min_size=11, max_size=11),
)
def test_binop_nested(get_contract, assert_tx_failed, values, ops):
    variables = "abcdefghij"
    input_value = ",".join(f"{i}: int128" for i in variables[: len(values)])
    return_value = " ".join(f"{a} {b}" for a, b in zip(variables[: len(values)], ops))
    return_value = return_value.rsplit(maxsplit=1)[0]

    source = f"""
@external
def foo({input_value}) -> int128:
    return {return_value}
    """
    contract = get_contract(source)

    literal_op = " ".join(f"{a} {b}" for a, b in zip(values, ops))
    literal_op = literal_op.rsplit(maxsplit=1)[0]

    vyper_ast = vy_ast.parse_to_ast(literal_op)

    try:
        vy_ast.folding.replace_literal_ops(vyper_ast)
        expected = vyper_ast.body[0].value.value
        is_valid = True
    except ZeroDivisionException:
        is_valid = False

    if is_valid:
        assert contract.foo(*values) == expected
    else:
        assert_tx_failed(lambda: contract.foo(*values))
