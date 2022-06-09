import pytest

from vyper import ast as vy_ast
from vyper.semantics import validate_semantics


@pytest.mark.parametrize("bool_cond", [True, False])
def test_unaryop(get_contract, bool_cond):
    test_code = """
@external
def foo(a: bool) -> bool:
    return not a
    """

    expected_code = f"""
@external
def foo(a: bool) -> bool:
    return not {bool_cond}
    """

    vyper_ast = vy_ast.parse_to_ast(expected_code)
    validate_semantics(vyper_ast, None)
    old_node = vyper_ast.body[0].body[0].value
    new_node = old_node.evaluate()

    contract = get_contract(test_code)
    assert contract.foo(bool_cond) == new_node.value


@pytest.mark.parametrize("count", range(2, 11))
@pytest.mark.parametrize("bool_cond", [True, False])
def test_unaryop_nested(get_contract, bool_cond, count):
    test_code = f"""
@external
def foo(a: bool) -> bool:
    return {'not ' * count} a
    """

    replacement = ""
    if count % 2 == 1:
        replacement = "not "

    expected_code = f"""
@external
def foo(a: bool) -> bool:
    return {replacement}{bool_cond}
    """

    vyper_ast = vy_ast.parse_to_ast(expected_code)
    validate_semantics(vyper_ast, None)
    vy_ast.folding.replace_literal_ops(vyper_ast)
    expected = vyper_ast.body[0].body[0].value.value

    contract = get_contract(test_code)
    assert contract.foo(bool_cond) == expected
