import pytest

from vyper import (
    ast as vy_ast,
)


@pytest.mark.parametrize("bool_cond", [True, False])
def test_unary_op(get_contract, bool_cond):
    source = """
@public
def foo(a: bool) -> bool:
    return not a
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"not {bool_cond}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(bool_cond) == new_node.value
