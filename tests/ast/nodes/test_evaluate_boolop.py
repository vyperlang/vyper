from hypothesis import (
    given,
    settings,
    strategies as st,
)

from vyper import (
    ast as vy_ast,
)


@settings(deadline=500)
@given(a=st.booleans(), b=st.booleans(), c=st.booleans())
def test_boolop_and(get_contract, a, b, c):
    source = """
@public
def foo(a: bool, b: bool, c: bool) -> bool:
    return a and b and c
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} and {b} and {c}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(a, b, c) == new_node.value


@settings(deadline=500)
@given(a=st.booleans(), b=st.booleans(), c=st.booleans())
def test_boolop_or(get_contract, a, b, c):
    source = """
@public
def foo(a: bool, b: bool, c: bool) -> bool:
    return a or b or c
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{a} or {b} or {c}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(a, b, c) == new_node.value
