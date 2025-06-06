import pytest

from vyper import ast as vy_ast

OPERATOR_NODES = {
    "+": vy_ast.Add,
    "-": vy_ast.Sub,
    "*": vy_ast.Mult,
    "//": vy_ast.FloorDiv,
    "%": vy_ast.Mod,
}


@pytest.mark.parametrize("op", ["+", "-", "*", "//", "%"])
def test_binop_operators(op):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> uint256:
    return a {op} b

@external
def bar(a: uint256, b: uint256) -> uint256:
    return b {op} a
    """

    vyper_ast = vy_ast.parse_to_ast(source)

    operator_nodes = vyper_ast.get_descendants(OPERATOR_NODES[op])
    num_operator_nodes = len(operator_nodes)

    line_infos = set(
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) for n in operator_nodes
    )
    assert len(line_infos) == num_operator_nodes

    node_ids = set(n.node_id for n in operator_nodes)
    assert len(node_ids) == num_operator_nodes
