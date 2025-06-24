import pytest

from vyper import ast as vy_ast

# Note that this file only tests the correct generation of vyper AST nodes
# before typechecking, so the tests may use types that are invalid for a
# given operator

UNARY_OPERATOR_NODES = {"-": vy_ast.USub, "not": vy_ast.Not, "~": vy_ast.Invert}

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

COMPARISON_OPERATOR_NODES = {
    "==": vy_ast.Eq,
    "!=": vy_ast.NotEq,
    "<": vy_ast.Lt,
    "<=": vy_ast.LtE,
    ">": vy_ast.Gt,
    ">=": vy_ast.GtE,
    "in": vy_ast.In,
    "not in": vy_ast.NotIn,
}

BOOLEAN_OPERATOR_NODES = {"and": vy_ast.And, "or": vy_ast.Or}


def _check_unique_nodes(nodes: list[vy_ast.VyperNode]):
    line_infos = [(n.lineno, n.col_offset, n.end_lineno, n.end_col_offset) for n in nodes]
    assert len(set(line_infos)) == len(nodes)

    node_ids = [n.node_id for n in nodes]
    assert len(set(node_ids)) == len(nodes)


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

    _check_unique_nodes(vyper_ast.get_descendants(BINARY_OPERATOR_NODES[op]))


@pytest.mark.parametrize("op", UNARY_OPERATOR_NODES.keys())
def test_unary_operators(op):
    op_str = op
    if op == "not":
        op_str = op + " "

    source = f"""
@external
def foo(a: int256) -> int256:
    return {op_str}a

@external
def bar(a: int256) -> int256:
    x: int256 = {op_str}a
    return x
        """

    vyper_ast = vy_ast.parse_to_ast(source)

    _check_unique_nodes(vyper_ast.get_descendants(UNARY_OPERATOR_NODES[op]))


@pytest.mark.parametrize("op", COMPARISON_OPERATOR_NODES.keys())
def test_comparison_operators(op):
    source = f"""
@external
def foo(a: uint256, b: uint256) -> bool:
    return a {op} b

@external
def bar(a: uint256, b: uint256) -> bool:
    return b {op} a
    """

    vyper_ast = vy_ast.parse_to_ast(source)

    _check_unique_nodes(vyper_ast.get_descendants(COMPARISON_OPERATOR_NODES[op]))


@pytest.mark.parametrize("op", BOOLEAN_OPERATOR_NODES.keys())
def test_boolean_operators(op):
    source = f"""
@external
def foo(a: bool, b: bool) -> bool:
    return a {op} b

@external
def bar(a: bool, b: bool) -> bool:
    return b {op} a
    """

    vyper_ast = vy_ast.parse_to_ast(source)

    _check_unique_nodes(vyper_ast.get_descendants(BOOLEAN_OPERATOR_NODES[op]))
