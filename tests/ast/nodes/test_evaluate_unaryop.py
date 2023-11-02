import pytest

from vyper import ast as vy_ast
from vyper.semantics import validate_semantics


@pytest.mark.parametrize("bool_cond", [True, False])
def test_unaryop(get_contract, bool_cond):
    source = """
@external
def foo(a: bool) -> bool:
    return not a
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"not {bool_cond}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate(old_node.operand)

    assert contract.foo(bool_cond) == new_node.value


@pytest.mark.parametrize("count", range(2, 11))
@pytest.mark.parametrize("bool_cond", [True, False])
def test_unaryop_nested(get_contract, bool_cond, count):
    source = f"""
@external
def foo(a: bool) -> bool:
    return {'not ' * count} a
    """
    contract = get_contract(source)

    literal_op = f"{'not ' * count}{bool_cond}"
    expected = f"""
@external
def foo() -> bool:
    return {literal_op}
    """

    vyper_ast = vy_ast.parse_to_ast(expected)
    validate_semantics(vyper_ast, {})
    vy_ast.folding.replace_foldable_values(vyper_ast)
    expected = vyper_ast.body[0].body[0].value.value

    assert contract.foo(bool_cond) == expected
