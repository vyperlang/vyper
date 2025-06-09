import pytest

from vyper import ast as vy_ast

UNARY_OPERATOR_NODES = {
    "-": vy_ast.USub,
    "not": vy_ast.Not,
    "~": vy_ast.Invert,
}

BINARY_OPERATOR_NODES = {
    "+": vy_ast.Add,
    "-": vy_ast.Sub,
    "*": vy_ast.Mult,
    "/": vy_ast.Div,
    "//": vy_ast.FloorDiv,
    "%": vy_ast.Mod,
    "**": vy_ast.Pow,
    "<<": vy_ast.LShift,
    ">>": vy_ast.RShift,
    "|": vy_ast.BitOr,
    "^": vy_ast.BitXor,
    "&": vy_ast.BitAnd,
}

@pytest.mark.parametrize("op", BINARY_OPERATOR_NODES.keys())
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

    operator_nodes = vyper_ast.get_descendants(BINARY_OPERATOR_NODES[op])
    num_operator_nodes = len(operator_nodes)

    line_infos = set(
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) for n in operator_nodes
    )
    assert len(line_infos) == num_operator_nodes

    node_ids = set(n.node_id for n in operator_nodes)
    assert len(node_ids) == num_operator_nodes

@pytest.mark.parametrize("op", UNARY_OPERATOR_NODES.keys())
def test_unary_operators(op):
    op_str = op
    if op == "-":
        typ = "int256"
    elif op == "not":
        typ = "bool"
        op_str = op + " "
    elif op == "~":
        typ = "uint256"
    
    source = f"""
@external
def foo(a: {typ}) -> {typ}:
    return {op_str}a

@external
def bar(a: {typ}) -> {typ}:
    x: {typ} = {op_str}a
    return x
        """

    vyper_ast = vy_ast.parse_to_ast(source)

    operator_nodes = vyper_ast.get_descendants(UNARY_OPERATOR_NODES[op])
    num_operator_nodes = len(operator_nodes)

    line_infos = set(
        (n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) for n in operator_nodes
    )
    assert len(line_infos) == num_operator_nodes

    node_ids = set(n.node_id for n in operator_nodes)
    assert len(node_ids) == num_operator_nodes
