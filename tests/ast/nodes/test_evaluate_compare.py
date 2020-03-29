from hypothesis import (
    given,
    settings,
    strategies as st,
)

from vyper import (
    ast as vy_ast,
)


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_eq(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a == b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} == {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_ne(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a != b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} != {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_lt(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a < b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} < {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_le(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a <= b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} <= {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_gt(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a > b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} > {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_compare_ge(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> bool:
    return a >= b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} >= {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.lists(st.integers(), min_size=1, max_size=16))
def test_compare_in(left, right, get_contract):
    source = f"""
@public
def foo(a: int128, b: int128[{len(right)}]) -> bool:
    c: int128[{len(right)}] = b
    return a in c
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} in {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value
