import pytest

from tests.utils import parse_and_fold


@pytest.mark.parametrize("typ_name", ["decimal"])
def test_epsilon(get_contract, typ_name):
    source = f"""
@external
def foo() -> {typ_name}:
    return epsilon({typ_name})
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"epsilon({typ_name})")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo() == new_node.value
