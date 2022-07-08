import ast as python_ast
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.ast.annotation import annotate_python_ast
from vyper.ast.pre_parser import pre_parse
from vyper.exceptions import CompilerPanic, ParserException, SyntaxException, UnfoldableNode


def parse_to_ast(
    source_code: str, source_id: int = 0, contract_name: Optional[str] = None
) -> vy_ast.Module:
    """
    Parses a Vyper source string and generates basic Vyper AST nodes.

    Parameters
    ----------
    source_code : str
        The Vyper source code to parse.
    source_id : int, optional
        Source id to use in the `src` member of each node.

    Returns
    -------
    list
        Untyped, unoptimized Vyper AST nodes.
    """
    if "\x00" in source_code:
        raise ParserException("No null bytes (\\x00) allowed in the source code.")
    class_types, reformatted_code = pre_parse(source_code)
    try:
        py_ast = python_ast.parse(reformatted_code)
    except SyntaxError as e:
        # TODO: Ensure 1-to-1 match of source_code:reformatted_code SyntaxErrors
        raise SyntaxException(str(e), source_code, e.lineno, e.offset) from e
    annotate_python_ast(py_ast, source_code, class_types, source_id, contract_name)

    # Convert to Vyper AST.
    return vy_ast.get_node(py_ast)  # type: ignore


def ast_to_dict(ast_struct: Union[vy_ast.VyperNode, List]) -> Union[Dict, List]:
    """
    Converts a Vyper AST node, or list of nodes, into a dictionary suitable for
    output to the user.
    """
    if isinstance(ast_struct, vy_ast.VyperNode):
        return ast_struct.to_dict()
    elif isinstance(ast_struct, list):
        return [i.to_dict() for i in ast_struct]
    else:
        raise CompilerPanic(f'Unknown Vyper AST node provided: "{type(ast_struct)}".')


def dict_to_ast(ast_struct: Union[Dict, List]) -> Union[vy_ast.VyperNode, List]:
    """
    Converts an AST dict, or list of dicts, into Vyper AST node objects.
    """
    if isinstance(ast_struct, dict):
        return vy_ast.get_node(ast_struct)
    if isinstance(ast_struct, list):
        return [vy_ast.get_node(i) for i in ast_struct]
    raise CompilerPanic(f'Unknown ast_struct provided: "{type(ast_struct)}".')


def get_constant_value(node: vy_ast.VyperNode) -> Any:
    """
    Helper function to retrieve the value of a constant.

    Returns None if unable to retrieve a literal value.
    """
    if isinstance(node, (vy_ast.BinOp, vy_ast.UnaryOp, vy_ast.BoolOp, vy_ast.Compare)):
        return node.evaluate()  # type: ignore

    if isinstance(node, vy_ast.Constant):
        return node.value

    if isinstance(node, vy_ast.Name):
        # Check for builtin environment constants
        from vyper.ast.folding import BUILTIN_CONSTANTS

        if node.id in BUILTIN_CONSTANTS:
            return BUILTIN_CONSTANTS[node.id]["value"]

        # Check for user-defined constants
        vyper_module = node.get_ancestor(vy_ast.Module)
        for n in vyper_module.get_children(vy_ast.AnnAssign):
            # Ensure that the AnnAssign is a constant variable definition
            if not ("type" in n._metadata and n._metadata["type"].is_constant):
                continue

            if node.id == n.target.id:
                return get_constant_value(n.value)

    if isinstance(node, vy_ast.Call) and isinstance(node.func, vy_ast.Name):
        name = node.func.id
        from vyper.builtin_functions import DISPATCH_TABLE

        func = DISPATCH_TABLE.get(name)
        if func is None or not hasattr(func, "evaluate"):
            return None

        try:
            value = func.evaluate(node).value  # type: ignore
            return value
        except UnfoldableNode:
            return None

    if isinstance(node, vy_ast.List):
        ret = [get_constant_value(i) for i in node.elements]
        if None in ret:
            return None
        return ret

    return None


def get_folded_numeric_literal(node: vy_ast.VyperNode) -> Union[int, Decimal]:
    """
    Helper function to derive folded value of literal ops or literal
    """
    val = get_constant_value(node)
    if not isinstance(val, (int, Decimal)):
        raise UnfoldableNode
    return val
