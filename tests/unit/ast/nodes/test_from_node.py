from vyper import ast as vy_ast


def test_output_class():
    old_node = vy_ast.parse_to_ast("foo = 42")
    new_node = vy_ast.Int.from_node(old_node, value=666)

    assert isinstance(new_node, vy_ast.Int)


def test_source():
    old_node = vy_ast.parse_to_ast("foo = 42")
    new_node = vy_ast.Int.from_node(old_node, value=666)

    assert old_node.src == new_node.src
    assert old_node.node_source_code == new_node.node_source_code


def test_kwargs():
    old_node = vy_ast.parse_to_ast("42").body[0].value
    new_node = vy_ast.Int.from_node(old_node, value=666)

    assert old_node.value == 42
    assert new_node.value == 666


def test_new_node_has_no_parent():
    old_node = vy_ast.parse_to_ast("foo = 42")
    new_node = vy_ast.Int.from_node(old_node, value=666)

    assert new_node._parent is None
    assert new_node._depth == 0
