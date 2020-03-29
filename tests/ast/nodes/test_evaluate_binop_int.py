from hypothesis import (
    example,
    given,
    settings,
    strategies as st,
)

from vyper import (
    ast as vy_ast,
)


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_binop_add(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> int128:
    return a + b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} + {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


# strategy bounds values ensure results do not overflow
@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers())
def test_binop_sub(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> int128:
    return a - b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} - {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.integers(min_value=-2**32, max_value=2**32),
    right=st.integers(min_value=-2**32, max_value=2**32),
)
def test_binop_mul(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> int128:
    return a * b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} * {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(min_value=0), right=st.integers(min_value=1))
def test_binop_div(left, right, get_contract):
    source = """
@public
def foo(a: uint256, b: uint256) -> uint256:
    return a / b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} / {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers().filter(lambda x: x != 0))
def test_binop_sdiv(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> int128:
    return a / b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} / {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(min_value=0), right=st.integers(min_value=1))
def test_binop_mod(left, right, get_contract):
    source = """
@public
def foo(a: uint256, b: uint256) -> uint256:
    return a % b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} % {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(left=st.integers(), right=st.integers().filter(lambda x: x != 0))
def test_binop_smod(left, right, get_contract):
    source = """
@public
def foo(a: int128, b: int128) -> int128:
    return a % b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} % {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value


@settings(max_examples=20, deadline=500)
@given(
    left=st.integers(min_value=2, max_value=245),
    right=st.integers(min_value=0, max_value=16),
)
@example(left=0, right=0)
@example(left=0, right=1)
def test_binop_pow(left, right, get_contract):
    source = """
@public
def foo(a: uint256, b: uint256) -> uint256:
    return a ** b
    """
    contract = get_contract(source)

    vyper_ast = vy_ast.parse_to_ast(f"{left} ** {right}")
    old_node = vyper_ast.body[0].value
    new_node = old_node.evaluate()

    assert contract.foo(left, right) == new_node.value
