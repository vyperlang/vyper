from vyper import ast as vy_ast


def test_order():
    node = vy_ast.parse_to_ast("1 + 2").body[0].value
    assert node.get_children() == [node.left, node.op, node.right]


def test_order_reversed():
    node = vy_ast.parse_to_ast("1 + 2").body[0].value
    assert node.get_children(reverse=True) == [node.right, node.op, node.left]


def test_type_filter():
    node = vy_ast.parse_to_ast("[1, 2.0, 'three', 4, 0x05]").body[0].value
    assert node.get_children(vy_ast.Int) == [node.elements[0], node.elements[3]]


def test_dict_filter():
    node = vy_ast.parse_to_ast("[foo, foo(), bar, bar()]").body[0].value
    assert node.get_children(filters={"func.id": "foo"}) == [node.elements[1]]


def test_only_returns_children():
    node = vy_ast.parse_to_ast("[1, 2, (3, 4), 5]").body[0].value
    assert node.get_children() == node.elements
