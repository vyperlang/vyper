import pytest

from tests.utils import parse_and_fold


@pytest.mark.parametrize("bool_cond", [True, False])
def test_unaryop(get_contract, bool_cond):
    source = """
@external
def foo(a: bool) -> bool:
    return not a
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"not {bool_cond}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

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
    vyper_ast = parse_and_fold(literal_op)
    new_node = vyper_ast.body[0].value.get_folded_value()
    expected = new_node.value

    assert contract.foo(bool_cond) == expected
