from tests.ast_utils import deepequals
from vyper import ast as vy_ast


def test_compare_different_node_clases():
    vyper_ast = vy_ast.parse_to_ast("foo = 42")
    left = vyper_ast.body[0].target
    right = vyper_ast.body[0].value

    assert not deepequals(left, right)


def test_compare_different_nodes_same_class():
    vyper_ast = vy_ast.parse_to_ast("[1, 2]")
    left, right = vyper_ast.body[0].value.elements

    assert not deepequals(left, right)


def test_compare_different_nodes_same_value():
    vyper_ast = vy_ast.parse_to_ast("[1, 1]")
    left, right = vyper_ast.body[0].value.elements

    assert not deepequals(left, right)


def test_compare_similar_node():
    # test equality without node_ids
    left = vy_ast.Int(value=1)
    right = vy_ast.Int(value=1)

    assert deepequals(left, right)


def test_compare_same_node():
    vyper_ast = vy_ast.parse_to_ast("42")
    node = vyper_ast.body[0].value

    assert deepequals(node, node)
