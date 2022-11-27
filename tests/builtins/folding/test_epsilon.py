import pytest

from vyper import ast as vy_ast
from vyper.builtins import functions as vy_fn


@pytest.mark.parametrize("typ_name", ["decimal"])
def test_epsilon(get_contract, typ_name):
    source = f"""
@external
def foo() -> {typ_name}:
    return epsilon({typ_name})
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"epsilon({typ_name})")
    old_node = vyper_ast.body[0].value
    new_node = vy_fn.DISPATCH_TABLE["epsilon"].evaluate(old_node)

    assert contract.foo() == new_node.value
