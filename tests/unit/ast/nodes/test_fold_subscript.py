import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tests.utils import parse_and_fold
from vyper.compiler import compile_code
from vyper.exceptions import ArrayIndexException


@pytest.mark.fuzzing
@settings(max_examples=50)
@given(
    idx=st.integers(min_value=0, max_value=9),
    array=st.lists(st.integers(), min_size=10, max_size=10),
)
def test_subscript(get_contract, array, idx):
    source = """
@external
def foo(array: int128[10], idx: uint256) -> int128:
    return array[idx]
    """
    contract = get_contract(source)

    vyper_ast = parse_and_fold(f"{array}[{idx}]")
    old_node = vyper_ast.body[0].value
    new_node = old_node.get_folded_value()

    assert contract.foo(array, idx) == new_node.value


def test_negative_index():
    source = """
@external
def foo(array: int128[10]) -> int128:
    return array[0 - 1]
    """
    with pytest.raises(ArrayIndexException):
        compile_code(source)


def test_oob_index():
    source = """
@external
def foo(array: int128[10]) -> int128:
    return array[9 + 1]
    """
    with pytest.raises(ArrayIndexException):
        compile_code(source)


failing_list = [
    "MAX: constant(DynArray[uint256, 10]) = [1, 2, 3]",
    "MAX: constant(uint256[3]) = [1, 2, 3]",
    "MAX: constant((uint256, uint256, uint256)) = (1, 2, 3)",
]


@pytest.mark.parametrize("decl", failing_list)
def test_oob_index_for_subscriptable_types(decl):
    source = f"""
{decl}
a: constant(uint256) = MAX[3]

@external
def foo() -> uint256:
    return a
    """
    with pytest.raises(ArrayIndexException):
        compile_code(source)


def test_oob_index_subscript_within_subscript():
    source = """
MAX: constant(uint256[3]) = [1, 2, 3]
a: constant(uint256) = MAX[MAX[0]+MAX[1]]

@external
def foo() -> uint256:
    return a
    """
    with pytest.raises(ArrayIndexException):
        compile_code(source)


def test_oob_index_literal_array():
    source = """
@external
def foo() -> uint256:
    return [[1], [2], [3], [4]][0][1]
    """
    with pytest.raises(ArrayIndexException):
        compile_code(source)
