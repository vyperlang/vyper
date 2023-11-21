import pytest

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic


def test_assumptions():
    # ASTs generated separately from the same source should compare equal
    test_tree = vy_ast.parse_to_ast("foo = 42")
    expected_tree = vy_ast.parse_to_ast("foo = 42")
    assert vy_ast.compare_nodes(test_tree, expected_tree)

    # ASTs generated separately with different source should compare not-equal
    test_tree = vy_ast.parse_to_ast("foo = 42")
    expected_tree = vy_ast.parse_to_ast("bar = 666")
    assert not vy_ast.compare_nodes(test_tree, expected_tree)


def test_simple_replacement():
    test_tree = vy_ast.parse_to_ast("foo = 42")
    expected_tree = vy_ast.parse_to_ast("bar = 42")

    old_node = test_tree.body[0].target
    new_node = vy_ast.parse_to_ast("bar").body[0].value

    test_tree.replace_in_tree(old_node, new_node)

    assert vy_ast.compare_nodes(test_tree, expected_tree)


def test_list_replacement_similar_nodes():
    test_tree = vy_ast.parse_to_ast("foo = [1, 1, 1, 1, 1]")
    expected_tree = vy_ast.parse_to_ast("foo = [1, 1, 31337, 1, 1]")

    old_node = test_tree.body[0].value.elements[2]
    new_node = vy_ast.parse_to_ast("31337").body[0].value

    test_tree.replace_in_tree(old_node, new_node)

    assert vy_ast.compare_nodes(test_tree, expected_tree)


def test_parents_children():
    test_tree = vy_ast.parse_to_ast("foo = 42")

    old_node = test_tree.body[0].target
    parent = old_node.get_ancestor()

    new_node = vy_ast.parse_to_ast("bar").body[0].value
    test_tree.replace_in_tree(old_node, new_node)

    assert old_node.get_ancestor() == new_node.get_ancestor()

    assert old_node not in parent.get_children()
    assert new_node in parent.get_children()

    assert old_node not in test_tree.get_descendants()
    assert new_node in test_tree.get_descendants()


def test_cannot_replace_twice():
    test_tree = vy_ast.parse_to_ast("foo = 42")
    old_node = test_tree.body[0].target

    new_node = vy_ast.parse_to_ast("42").body[0].value

    test_tree.replace_in_tree(old_node, new_node)

    with pytest.raises(CompilerPanic):
        test_tree.replace_in_tree(old_node, new_node)
