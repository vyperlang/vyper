import ast as python_ast
from typing import Dict, List, Optional, Union

from vyper.ast import nodes as vy_ast
from vyper.ast.annotation import annotate_python_ast
from vyper.ast.pre_parser import pre_parse
from vyper.exceptions import CompilerPanic, ParserException, SyntaxException


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
