from vyper import ast as vy_ast


def test_compare_different_node_clases():
    vyper_ast = vy_ast.parse_to_ast("foo = 42")
    left = vyper_ast.body[0].target
    right = vyper_ast.body[0].value

    assert left != right
    assert not vy_ast.compare_nodes(left, right)


def test_compare_different_nodes_same_class():
    vyper_ast = vy_ast.parse_to_ast("[1, 2]")
    left, right = vyper_ast.body[0].value.elements

    assert left != right
    assert not vy_ast.compare_nodes(left, right)


def test_compare_different_nodes_same_value():
    vyper_ast = vy_ast.parse_to_ast("[1, 1]")
    left, right = vyper_ast.body[0].value.elements

    assert left != right
    assert vy_ast.compare_nodes(left, right)


def test_compare_complex_nodes_same_value():
    vyper_ast = vy_ast.parse_to_ast("[{'foo':'bar', 43:[1,2,3]}, {'foo':'bar', 43:[1,2,3]}]")
    left, right = vyper_ast.body[0].value.elements

    assert left != right
    assert vy_ast.compare_nodes(left, right)


def test_compare_same_node():
    vyper_ast = vy_ast.parse_to_ast("42")
    node = vyper_ast.body[0].value

    assert node == node
    assert vy_ast.compare_nodes(node, node)
